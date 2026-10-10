"""Offline-only native host fixture: actual server, YouTube MockTransport, no live mode."""
import asyncio
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import httpx
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.interfaces.mcp import server
control=Path(os.environ['IGNIS_OFFLINE_CONTROL'])
async def response(request):
    if request.url.host!='www.googleapis.com':raise AssertionError('Unexpected offline destination')
    with (control/'calls.jsonl').open('a') as out:out.write(json.dumps({'path':request.url.path})+'\n')
    if request.url.path.endswith('/search'):
        (control/'collector-entered').touch()
        while not (control/'release-collector').exists():await asyncio.sleep(.02)
        return httpx.Response(200,json={'items':[{'id':{'videoId':'offline-video'}}]})
    return httpx.Response(200,json={'items':[{'id':'offline-video','snippet':{
        'title':'Offline tutorial','description':'Offline public description','channelTitle':'Offline channel',
        'channelId':'offline-channel','publishedAt':datetime.now(timezone.utc).isoformat()},
        'statistics':{'viewCount':'10','likeCount':'1','commentCount':'0'}}]})
YouTubeDataPlugin._client=lambda self,**kwargs:httpx.AsyncClient(transport=httpx.MockTransport(response),**kwargs)
original_dashboard=server._MissionRelayRuntime.started_dashboard
async def observed_dashboard(self,mission,journal):
    try:
        result=await original_dashboard(self,mission,journal)
        (control/'dashboard-diagnostic.json').write_text(json.dumps({
            'status':result.get('status'),'reason_code':result.get('reason_code')}))
        return result
    except Exception as error:
        import traceback
        frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'name':frame.name}
            for frame in traceback.extract_tb(error.__traceback__)]
        (control/'dashboard-diagnostic.json').write_text(json.dumps({'error_type':type(error).__name__,'frames':frames}))
        raise
server._MissionRelayRuntime.started_dashboard=observed_dashboard
server.main()
