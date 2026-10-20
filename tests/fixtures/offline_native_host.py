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
    if request.url.host!='www.googleapis.com':
        raise AssertionError('Unexpected offline destination')
    with (control/'calls.jsonl').open('a') as out:
        out.write(json.dumps({'path':request.url.path})+'\n')
    if request.url.path.endswith('/search'):
        (control/'collector-entered').touch()
        while not (control/'release-collector').exists():
            await asyncio.sleep(.02)
        return httpx.Response(200,json={'items':[{'id':{'videoId':'offline-video'}}]})
    return httpx.Response(200,json={'items':[{'id':'offline-video','snippet':{
        'title':'Offline tutorial','description':'Offline public description','channelTitle':'Offline channel',
        'channelId':'offline-channel','publishedAt':datetime.now(timezone.utc).isoformat()},
        'statistics':{'viewCount':'10','likeCount':'1','commentCount':'0'}}]})
YouTubeDataPlugin._client=lambda self,**kwargs:httpx.AsyncClient(transport=httpx.MockTransport(response),**kwargs)
server.main()
