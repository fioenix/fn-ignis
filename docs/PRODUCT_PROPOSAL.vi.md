---
title: "Ignis Product Proposal — Evidence-Grounded Social Market Research Agent"
status: approved
date: 2026-09-29
owner: FINOLABS
approved: 2026-09-29
language: vi
---

# Ignis Product Proposal

## Evidence-Grounded Social Market Research Agent

> **Product thesis:** Ignis giúp founder, operator, analyst và consultant tự thu thập bằng chứng social cho một quyết định kinh doanh cụ thể, phân tích bằng một phương pháp có thể kiểm tra, và chủ động phản biện niềm tin ban đầu thay vì tìm dữ liệu để xác nhận nó.

## 1. Executive summary: Quyết định được đề xuất

Ignis nên rời category “autonomous trend radar” để trở thành một **agent nghiên cứu thị trường social theo nhiệm vụ, có evidence gate và được thiết kế để chống confirmation bias**.

Ignis chỉ khởi động khi user hoặc host agent giao một nhiệm vụ rõ ràng. Sau đó, nó tự chủ trong phạm vi mission đã xác nhận: chọn connector phù hợp, mở rộng query, thu thập observation, kiểm tra chất lượng bằng chứng, chạy các phép phân tích cần thiết và tạo artifact. Ignis dừng khi hoàn tất mission, chạm giới hạn scope, cần quyền truy cập mới hoặc không đủ bằng chứng. Không có Daily Auto Collect, scheduler, daemon chờ sẵn hay silent expansion ngoài nhiệm vụ.

Sản phẩm có hai capability family mà user có thể dùng độc lập hoặc nối tiếp:

1. **`ignis-collect`** — skills và connectors tích hợp sẵn để thu thập dữ liệu thực tế từ các social surface cho một nhiệm vụ cụ thể.
2. **`ignis-analyze`** — skill Senior Market Analytics cùng report/dashboard templates để biến corpus đã được Ignis thu thập và qualify thành insight có cơ sở.

Hai family dùng chung một **evidence control plane**. Đây là hạ tầng nội bộ, không phải capability family thứ ba. Nó giữ mission manifest, provenance, trạng thái từng kênh, corpus digest, qualification, counterevidence và claim ledger. Nếu bỏ lớp này, Ignis chỉ còn là một bộ connector cộng prompt template, tức là hai loại capability đã bị commoditize.

### Trạng thái hoàn thành mong muốn

Proposal thành công khi được hiện thực hóa thành một sản phẩm cho phép user:

- giao một câu hỏi kinh doanh hoặc một nhiệm vụ social listening rõ ràng;
- biết Ignis sẽ thu thập ở đâu, trong giới hạn nào và cần quyền gì;
- xem được dữ liệu nào đã thu, dữ liệu nào thiếu và vì sao;
- thấy mỗi kết luận dựa trên observation nào và phản chứng nào đã được xem xét;
- nhận một strategic verdict khi evidence đủ, hoặc một gap report có hành động tiếp theo khi evidence chưa đủ;
- kiểm tra lại cách Ignis đi từ câu hỏi đến kết luận mà không phải tin vào giọng văn tự tin của model.

Thành công không phải là số connector, số report được tạo hay số observation đã lưu. Thành công là **user ra quyết định tốt hơn và biết giới hạn của bằng chứng đã dùng**.

## 2. Evidence base và ranh giới của proposal

Proposal tổng hợp hai nguồn nền:

- Deep research ngày 29/09/2026 về open-source landscape, commercial social intelligence, data providers và Perplexity; research archive giữ 52 nguồn, 53 evidence rows và 18 claim records. Kết quả verification ghi nhận 13 claim được support, 5 claim partial và 0 factual claim unsupported. Nghiên cứu chưa cài chạy các OSS candidate và chưa chạy Perplexity Computer bằng tài khoản đăng nhập; proposal vẫn chịu các giới hạn này.
- Nội dung trực tiếp của deck [`Product Mindset v2.dc.html`](https://claude.ai/design/p/ae499fce-9a30-4825-a606-e2c22ca6aa39?file=Product+Mindset+v2.dc.html), dùng để chuyển Outcome Thinking, Design Thinking và Critical Thinking thành product behaviour.

Proposal không tuyên bố target architecture đã được triển khai. Repository hiện vẫn có mô hình radar chạy nền và các contract liên quan scheduled ingress. Việc bỏ kiến trúc đó cần ADR/spec, sửa constitution, runtime, bootstrap, tài liệu và backlog đồng bộ trước khi Ignis có thể quảng bá “on-demand by construction”.

Proposal cũng không khẳng định social data đáng tin hơn dữ liệu trả phí. Social data vẫn có selection bias, platform-access bias, missingness và giới hạn pháp lý. Khác biệt của Ignis nằm ở **quyền kiểm soát quá trình thu thập, khả năng audit và phương pháp xử lý uncertainty**, không nằm ở giả định rằng dữ liệu miễn phí mặc nhiên đúng.

## 3. Vấn đề cần giải quyết

### 3.1. Người dùng đang mắc kẹt giữa hai lựa chọn không tốt

Ở một đầu, commercial social-listening suites bán coverage, lịch sử dữ liệu và workflow enterprise. Brandwatch quảng bá dữ liệu lịch sử từ năm 2008; Sprinklr và Talkwalker quảng bá độ phủ trên nhiều social/digital channels. Đây là lợi thế thật mà một collector self-hosted mới không nên giả vờ có ([Brandwatch](https://www.brandwatch.com/products/consumer-research/), [Sprinklr](https://www.sprinklr.com/products/consumer-intelligence/social-listening/), [Talkwalker](https://www.talkwalker.com/products/social-listening)). Nhưng với founder, consultant hoặc đội nhỏ, dữ liệu và phương pháp xử lý thường nằm trong black box của vendor, còn giá và quyền tái sử dụng tạo thêm dependency.

Ở đầu kia, user có thể tự dùng scraper, API, Bright Data, Apify hoặc các project open source. Họ kiểm soát output tốt hơn nhưng phải tự thiết kế query, sampling, deduplication, provenance, relevance, quality gate và phương pháp phân tích. Một composable stack như Zeeschuimer/minet → 4CAT → GPT Researcher → Superset có thể thay gần như mọi primitive của Ignis, nhưng integration burden và research responsibility vẫn thuộc user ([Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer), [4CAT](https://github.com/digitalmethodsinitiative/4cat), [GPT Researcher](https://github.com/assafelovic/gpt-researcher), [Apache Superset](https://github.com/apache/superset)).

Các sản phẩm deep research phổ dụng xử lý rất tốt khâu synthesis và tạo artifact. Perplexity có thể tìm kiếm rộng, đọc file, dùng connector, chạy browser workflow và tạo report, spreadsheet, deck hoặc dashboard. Với nhu cầu “một market brief có nguồn”, user đã có một substitute mạnh ([Perplexity Deep Research](https://www.perplexity.ai/en-GB/hub/products/deep-research), [Perplexity Computer](https://www.perplexity.ai/en-GB/products/computer)). Nhưng source citation không tự tạo ra một social corpus đầy đủ, replayable hoặc một rule buộc hệ thống từ chối kết luận khi required channel thất bại.

### 3.2. Vấn đề sâu hơn là confirmation bias

Market research thường bắt đầu từ một ý tưởng mà người nghiên cứu đã muốn tin. Từ khóa họ chọn, platform họ mở, câu hỏi họ đặt và evidence họ giữ lại đều có thể vô thức phục vụ một mục tiêu: chứng minh ý tưởng đúng. AI khuếch đại rủi ro này vì nó có thể tổng hợp một narrative trơn tru từ một corpus lệch và trình bày suy luận bằng giọng chắc chắn.

Vì thế, vấn đề cốt lõi không phải là “thiếu dữ liệu” hay “thiếu dashboard”:

> Người ra quyết định thiếu một research instrument đủ dễ dùng để tự nghe thị trường, nhưng đủ kỷ luật để phân biệt observation, inference và assumption; chủ động tìm phản chứng; và dừng kết luận khi evidence không đủ.

### 3.3. Ai chịu chi phí hôm nay

| Người dùng | Trải nghiệm hiện tại | Chi phí họ trả |
|---|---|---|
| Founder / operator | Tự search social, lưu link rời rạc, hỏi AI tổng hợp | Quyết định dựa trên mẫu thuận tiện và niềm tin ban đầu |
| Market analyst / researcher | Ghép nhiều tool, làm sạch và dẫn nguồn thủ công | Thời gian integration, audit và bảo vệ phương pháp |
| Consultant / agency | Cần report nhanh nhưng vẫn phải giải thích nguồn cho client | Uy tín nếu citation không thực sự support claim |
| Small consumer team | Không mua được licensed data rộng hoặc không tin black box | Bỏ cuộc, dùng proxy yếu, hoặc trả tiền cho dữ liệu không kiểm chứng được |

## 4. Cơ hội sản phẩm và competitive wedge

Deep research cho thấy Ignis không có moat nếu chỉ nói “autonomous research”, “multi-source social listening”, “report có citation” hoặc “dashboard đẹp”. TrendScope, Radar Intelligence, Jev Social/socai, 4CAT/Zeeschuimer, GPT Researcher và các sản phẩm deep research đã cung cấp phần lớn primitive riêng lẻ ([TrendScope](https://github.com/mamboyepez17/trendscope), [Radar Intelligence](https://github.com/Scognamiglio1969/radar-intelligence), [Jev Social](https://github.com/socai-io/jev-social), [socai](https://github.com/socai-io/socai)).

Ba hướng chiến lược đã được xem xét:

| Hướng | Ưu điểm | Ai trả giá | Kết luận |
|---|---|---|---|
| Open-source Brandwatch | Category quen thuộc, roadmap theo feature dễ hiểu | Đội Ignis phải chạy cuộc đua coverage, history và enterprise workflow vô hạn | Không chọn |
| Perplexity for social | Câu chuyện đơn giản, đầu ra hấp dẫn | User nhận thêm một lớp synthesis nhưng không có trust boundary mới | Không chọn |
| Evidence-gated social market research | Bám đúng nhu cầu tự nghe social và biết kết luận dựa trên gì | Ignis chịu complexity ở evidence contract; user đôi khi nhận refusal | **Chọn** |

Competitive wedge được đề xuất:

> **Ignis là research instrument dành cho những quyết định mà nguồn bằng chứng social, cách thu thập, dữ liệu thiếu và phản chứng quan trọng hơn tốc độ tạo ra một câu trả lời đẹp.**

Owner đã chọn founder, operator, analyst và consultant nghiên cứu consumer market tại Việt Nam làm beachhead pilot chính thức. Quyết định này xác định nơi Ignis bắt đầu kiểm chứng, không mặc nhiên chứng minh product-market fit. Beachhead tận dụng năng lực ngôn ngữ, connector và case-study hiện tại mà không tuyên bố Ignis đã bao phủ mọi quốc gia hoặc vertical.

### 4.1. Vì sao đây là thời điểm phù hợp và Ignis có cơ sở để thử

Khả năng tổng hợp kèm citation đang nhanh chóng trở thành commodity: general research agents đã có search, file analysis, connector và artifact generation; hệ sinh thái MCP/API còn cho phép chúng gọi thêm nguồn dữ liệu chuyên biệt. Vì thế, định vị quanh lời hứa “AI research nhanh hơn” ngày càng yếu. Đồng thời, chính hệ sinh thái này tạo distribution path cho một evidence service chuyên sâu mà các host agent có thể gọi khi quyết định cần mức kiểm chứng cao hơn.

Ignis có cơ sở để thử wedge này vì codebase đã có các nền móng khó nhất của một evidence control plane: mission/workspace, provenance, channel state và decision-grade evidence qualification. Plan 008 cùng phần đồng bộ backlog đã được merge vào `main` qua PR #34 và #35. Tuy nhiên, đó mới là **implementation foundation**, không phải bằng chứng product-market fit và cũng không có nghĩa product reset đã ship: chưa có release mới chứa thay đổi này, thay đổi chưa được áp dụng cho long-lived database và runtime hiện vẫn giữ các contract scheduled/daily cũ.

Vì vậy, lợi thế thực tế của Ignis không phải “đã hoàn thành sản phẩm”, mà là **có điểm xuất phát kỹ thuật phù hợp để kiểm chứng category mới nhanh hơn một đội phải xây evidence lineage từ đầu**. Quyền thắng chỉ hình thành nếu pilot chứng minh user thật sự đổi quyết định hoặc tin tưởng verdict hơn nhờ counterevidence, missingness và claim-level provenance.

### 4.2. Bản đồ năng lực cạnh tranh

[Mở radar năng lực cạnh tranh của Ignis](diagrams/ignis-competitive-capability-radar.html).

Radar không đo market share, doanh thu hay hiệu năng thực tế. Nó biểu diễn một giả thuyết định vị trên thang năng lực 1–5, dựa trên capability đã được tài liệu hóa: `1` là không phải năng lực cốt lõi; `3` là đã có hỗ trợ native nhưng còn giới hạn; `5` là năng lực được tích hợp, có thể kiểm tra và đóng vai trò rõ ràng trong value proposition. “Nhu cầu thị trường mục tiêu” là đường chuẩn thiết kế, không phải một đối thủ.

| Archetype | Social | Coverage | Audit | Challenge | Action |
|---|---:|---:|---:|---:|---:|
| Nhu cầu thị trường mục tiêu | 4 | 3 | 5 | 5 | 5 |
| Ignis target product | 4 | 2 | 5 | 5 | 4 |
| Enterprise social suites | 5 | 5 | 2 | 1 | 4 |
| General research agents | 2 | 4 | 2 | 1 | 5 |
| Composable OSS stack | 4 | 3 | 4 | 2 | 2 |

Hình cho thấy lựa chọn chiến lược: Ignis không thắng bằng độ phủ dữ liệu, nơi enterprise suites có lợi thế cấu trúc. Wedge nằm ở `Audit` và `Challenge`: biến provenance, missingness, counterevidence và refusal gate thành năng lực mặc định của một research instrument. Khoảng trống cần pilot kiểm chứng là `Action`: phương pháp tốt chỉ có giá trị khi verdict thực sự làm thay đổi hoặc làm rõ quyết định tiếp theo của user.

## 5. Định vị

- **Category:** Evidence-grounded social market research agent
- **Primary audience:** founder, operator, analyst, consultant và đội nhỏ cần research có thể audit nhưng không muốn phụ thuộc vào opaque purchased datasets
- **Primary job:** biến một câu hỏi kinh doanh thành một corpus social có provenance, rồi chỉ tạo những insight mà corpus đó đủ sức bảo vệ
- **Deployment stance:** open-source, local-first, self-hosted by default; có thể được gọi từ nhiều host agent
- **Not:** always-on social monitoring, generic AI search, scraper marketplace, BI platform hoặc commercial data firehose

### One-liner

> **Ignis là agent nghiên cứu thị trường social mã nguồn mở, chỉ chạy theo nhiệm vụ: tự thu thập bằng chứng cho một câu hỏi kinh doanh, chủ động tìm phản chứng, giữ lại nguồn gốc của từng observation và từ chối kết luận khi dữ liệu chưa đủ.**

### Brand promise

> **Own the evidence. Challenge the inference.**

### Điều Ignis không được hứa

- Không hứa “complete market view”.
- Không hứa social data mặc nhiên đáng tin hơn commercial data.
- Không hứa zero-cost; user vẫn trả API quota, compute, storage, maintenance và verification.
- Không hứa user có quyền sở hữu hoặc tái sử dụng không giới hạn nội dung public đã thu thập.
- Không dùng Opportunity Index như một oracle hoặc thay thế judgment.
- Không dùng “scientific” như nhãn marketing nếu report không disclose sample frame, query, preprocessing, missingness và limitation.

## 6. Ba product principles

Ba mindset không phải ba value để đặt trên landing page. Chúng là một vòng lặp vận hành có thể bắt lỗi:

> **Outcome đặt hướng → Design đi thử → Critical kiểm tra và có quyền sửa cả Outcome lẫn Design.**

### 6.1. Outcome Thinking: bắt đầu từ quyết định, không bắt đầu từ connector

Ignis không mở đầu bằng “mày muốn crawl TikTok hay Threads?”. Nó mở đầu bằng trạng thái user muốn thay đổi và quyết định họ cần đưa ra. Collection là output; một quyết định tốt hơn mới là outcome.

Với một Market mission, Ignis phải xác định tối thiểu:

- ai là người ra quyết định và ai chịu ảnh hưởng;
- vấn đề kinh doanh còn tồn tại khi bỏ tên công nghệ hoặc giải pháp;
- quyết định cần đưa ra sau research;
- hypothesis có thể bị bác bỏ;
- metric hoặc observable signal đại diện cho outcome;
- baseline/target nếu đây là bài toán tối ưu, hoặc success criteria vòng đầu nếu đây là bài toán khám phá;
- chi phí của false positive và false negative.

Attention mission vẫn được phép bắt đầu mà chưa có market hypothesis, vì mục tiêu của nó là khám phá tín hiệu đáng chú ý. Nhưng nó vẫn cần scope rõ và không được biến attention thành demand hoặc tạo Opportunity Index.

**Hành vi có thể kiểm tra:** report phải trả lời “quyết định nào được hỗ trợ, bị phản bác hoặc chưa thể đưa ra”, không chỉ liệt kê trend, sentiment và keyword.

### 6.2. Design Thinking: lắng nghe trước khi giải thích

Trong context của Ignis, năm bước Design Thinking trở thành các research behaviour sau:

1. **Empathize:** thu observation thật từ social surface; ưu tiên data và hành vi trước narrative. User input, interview answer hay keyword seed chỉ là đầu vào để đi tìm evidence, chưa phải evidence.
2. **Define:** kết tinh observation thành problem frame đủ rõ để hành động nhưng không khóa cứng vào một giải pháp. Một topic không tự động là một customer problem.
3. **Ideate:** giữ ít nhất ba cách giải thích cạnh tranh cho cùng một pattern, thay vì chọn ngay câu chuyện khớp niềm tin ban đầu.
4. **Prototype:** chạy probe nhỏ nhất đủ phân biệt các cách giải thích, chẳng hạn thêm một query, một platform, một comment sample hoặc một timeframe, trước khi mở rộng crawl.
5. **Test:** predeclare giả định và tín hiệu có thể làm nó sai; sau probe, quyết định giữ, sửa hay bỏ problem frame.

**Hành vi có thể kiểm tra:** mission journal phải cho thấy vì sao một probe được thêm và nó phân biệt giả thuyết nào; không được mở rộng collection chỉ vì “càng nhiều data càng tốt”.

### 6.3. Critical Thinking: thiết kế hệ thống để khó tự xác nhận mình

Critical Thinking là cơ chế bảo vệ giá trị khác biệt của Ignis. Mỗi Market mission cần một **Hypothesis Register** gồm:

- `core_hypothesis` — điều user đang tin hoặc muốn kiểm chứng;
- `alternative_hypotheses` — ít nhất hai cách giải thích khác có thể tạo cùng pattern;
- `null_hypothesis` — khả năng không có market signal đáng kể;
- `falsifiers` — observation nào sẽ làm core hypothesis yếu đi;
- `kill_criteria` — điều kiện khiến Ignis khuyến nghị không tiếp tục;
- `revision_rule` — khi nào phải viết lại outcome hoặc problem frame.

Collection plan phải có probe tìm evidence theo ba hướng: **supporting**, **contradicting** và **neutral/contextual**. Tiêu chuẩn kiểm tra phải đối xứng: evidence thuận ý không được kiểm tra lỏng hơn evidence trái ý. Contradiction không bị lọc như noise chỉ vì làm report khó kể chuyện.

Mọi analytical statement phải mang một trong các nhãn:

- `OBSERVATION` — nội dung thu trực tiếp;
- `MEASUREMENT` — phép tính có denominator và data-state rõ;
- `INFERENCE` — diễn giải từ một hoặc nhiều observation;
- `ASSUMPTION` — điều chưa được kiểm chứng;
- `RECOMMENDATION` — lựa chọn hành động dựa trên evidence và trade-off;
- `UNKNOWN` — chưa đủ bằng chứng để phân loại.

**Hành vi có thể kiểm tra:** report luôn có “Evidence against”, “Alternative explanations” và “What would change this verdict”. Một conclusion chỉ có evidence thuận mà không có kết quả tìm phản chứng phải bị gắn cờ `CONFIRMATION_RISK`.

## 7. Product contract

### 7.1. Bounded autonomy

Autonomy của Ignis bắt đầu sau explicit task assignment và kết thúc tại mission boundary. Một mission phải xác định:

- mục tiêu và decision context;
- geography, audience, language, timeframe;
- social surfaces được phép dùng;
- required và optional channels;
- auth/token/browser-session authority;
- budget hoặc quota nếu có;
- loại output mong muốn;
- stop conditions.

Trong boundary đó, Ignis tự quyết định thứ tự probe, query expansion, retry hợp lệ, sampling và phương pháp phân tích. Nó phải dừng và hỏi khi cần một quyền truy cập mới, thay đổi scope có thể làm đổi ý nghĩa nghiên cứu, sử dụng real social session chưa được cho phép hoặc phát sinh chi phí ngoài budget.

### 7.2. Social evidence is collected, not assumed

Brief, URL, keyword, file hoặc dataset user cung cấp là task input, seed hoặc context. Chúng không tự động trở thành decision evidence. Evidence chính phải được Ignis thu thập hoặc xác minh lại qua connector thuộc mission, với source identity, timestamp, query, collection path và connector revision.

Dataset được mua từ nguồn không minh bạch hoặc arbitrary CSV không được đi thẳng vào `ignis-analyze` như primary evidence. MVP không có đường import arbitrary dataset để tạo market verdict. Có thể xem xét verified-import contract trong tương lai, nhưng contract đó phải chứng minh provenance và sampling tương đương evidence do Ignis thu.

### 7.3. Fail closed, nhưng refusal phải hữu ích

Thiếu evidence không được biến thành zero. Connector failure không được biến thành absence. Unknown không được biến thành “không có nhu cầu”. Khi evidence dưới gate, Ignis trả:

- verdict nào bị giữ lại;
- gate nào chưa đạt;
- channel hoặc metric nào thiếu;
- điều gì đã được thử;
- probe nhỏ nhất có thể lấp gap;
- quyền, quota hoặc user choice cần thiết;
- phần kết luận nào vẫn an toàn để dùng.

Fail-closed mà chỉ nói “không đủ dữ liệu” là UX thất bại. Gap report phải biến refusal thành một next action có chi phí rõ ràng.

### 7.4. No silent cross-mission reuse

Observation được giữ immutable và có thể phục vụ audit hoặc mission khác, nhưng evidence qualification luôn scoped theo mission và exact Brief revision. Evidence cũ có thể xuất hiện như context hoặc lineage; nó không tự động trở thành support cho hypothesis mới.

### 7.5. Operator custody, không phải unrestricted ownership

Configured Ignis store lưu corpus, manifest và artifacts. Operator có thể self-host store này, đồng thời export và audit dữ liệu. Tuy nhiên, custody không trao quyền sở hữu hoặc tái phân phối không giới hạn đối với underlying content. Retention, redaction, platform terms, privacy và research ethics phải là một phần của connector/evidence policy, phù hợp với các cảnh báo trong [Meltwater Product Terms](https://www.meltwater.com/en/product-specific-terms), [Bright Data License Agreement](https://brightdata.com/license), [Apify Actor Terms](https://docs.apify.com/legal/actor-terms-and-conditions) và [Ten Simple Rules for Responsible Big Data Research](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1005399).

## 8. Target users, jobs và non-users

### 8.1. Beachhead pilot đã được chọn

Nhóm validation chính thức là founder, operator, independent analyst và consultant làm consumer-market research tại Việt Nam. Công việc của họ đủ gần với social signal để ngôn ngữ, pain point và contradictory evidence tạo ra giá trị, nhưng họ thường không có budget hoặc nhu cầu cho licensed firehose enterprise.

Pilot này phục vụ mục tiêu khám phá. Chưa có baseline về willingness-to-pay hay retention, nên proposal không bịa target doanh thu hoặc market share. Vòng pilot đầu phải tạo baseline.

### 8.2. Jobs to be done

**Explore:** “Khi chưa biết chủ đề nào đáng nghiên cứu, tao muốn quét có mục tiêu trên các social surface để thấy tín hiệu nổi lên mà không bị đánh lừa rằng attention chính là demand.”

**Investigate:** “Khi đang cân nhắc một market opportunity, tao muốn Ignis thu evidence liên quan đến target user, pain, demand, supply và objection để tao ra go / change / stop decision.”

**Challenge:** “Khi tao đã tin vào một ý tưởng, tao muốn hệ thống buộc tao nhìn thấy counterevidence và alternative explanations trước khi commit nguồn lực.”

**Defend:** “Khi cần trình bày với client hoặc team, tao muốn mỗi claim truy ngược được về observation, query, channel state và limitation.”

### 8.3. Ai không phải user trọng tâm

- Enterprise cần historical firehose, crisis alert 24/7 và coverage contract trên hàng chục kênh.
- User chỉ cần câu trả lời general web thật nhanh, không cần social-native corpus hoặc audit.
- Team muốn mua prebuilt market size và proprietary company/transaction data.
- Workflow cần auto-publish, engage hoặc thao tác tài khoản social; Ignis là read-oriented research instrument.

## 9. Product model

### 9.1. Hai capability family, hai analytical surface, một evidence core

Không được gộp hai trục này:

| Trục | Thành phần | Vai trò |
|---|---|---|
| Capability | `ignis-collect` | Thu thập social evidence theo mission |
| Capability | `ignis-analyze` | Phân tích qualified corpus và tạo artifact |
| Analytical surface | `ATTENTION` | Khám phá topic/cluster; không cần market hypothesis; không phát commercial verdict |
| Analytical surface | `MARKET` | Điều tra hypothesis theo confirmed Market Brief; có thể phát verdict nếu đủ evidence |
| Shared control plane | Evidence core | Giữ provenance, qualification, missingness, hypothesis register và claim binding |

User có thể gọi `ignis-collect` cho một tactical probe mà không cần full report. User cũng có thể yêu cầu một strategic Market mission, khi đó host agent phối hợp cả collection và analysis. `ignis-analyze` không nhận arbitrary external dataset làm primary evidence.

### 9.2. Logical architecture

| Thứ tự | Boundary | Input → output |
|---|---|---|
| 1 | Explicit user task | Ý định của user → nhiệm vụ có authority rõ |
| 2 | Mission / Brief contract | Nhiệm vụ → decision frame, hypothesis, scope và stop conditions |
| 3 | `ignis-collect` | Collection plan → raw observations và per-surface channel states |
| 4 | Evidence control plane | Raw corpus → provenance, qualification, evidence roles, corpus digest và sufficiency result |
| 5a | Insufficient branch | Failed gate → actionable gap report; không strategic verdict |
| 5b | `ignis-analyze` | Qualified corpus → source lenses, competing-hypothesis synthesis, claim ledger và report/dashboard |

Evidence control plane là authoritative service. Host agent có thể là Codex, Claude, Perplexity hoặc một client MCP khác; host được phép viết narrative khác, nhưng không được nâng một result `INSUFFICIENT_EVIDENCE` thành strategic verdict mà không tạo một mission/evidence frame mới.

### 9.3. Research workspace

Mỗi research được tổ chức trong một logical workspace, độc lập với chat session:

```text
<host-workspace>/.ignis/research/<research-slug>/
├── manifest.json
├── briefs/
├── missions/
├── evidence/
├── journals/
└── artifacts/
```

Configured Ignis database là canonical record store; các file đóng vai trò discovery entrypoint, projection, journal hoặc artifact. Attention context và Market evidence giữ lineage nhưng không trộn authority. Confirmed Market Brief là immutable; thay đổi hypothesis, target user hoặc problem tạo revision và mission mới.

## 10. Mission lifecycle

### 10.1. Bước 1: Assign

User giao nhiệm vụ rõ: tactical collection, Attention exploration hoặc Market investigation. Ignis không tự khởi động từ idle state và không tạo recurring schedule; recurring operation không thuộc product contract.

### 10.2. Bước 2: Frame the outcome

Host agent xác định outcome phù hợp với loại mission:

- **Tactical collect:** cần evidence gì, từ surface nào, trong timeframe nào.
- **Attention:** muốn quan sát phạm vi nào; ranking dựa trên freshness, momentum, coverage và diversity.
- **Market:** decision, target user, problem, geo, timeframe, hypothesis, falsifiers và cost of error.

Nếu yêu cầu đang chứa sẵn giải pháp, chẳng hạn “hãy chứng minh nên làm AI app X”, Ignis phải tách lại vấn đề kinh doanh trước khi thu thập.

### 10.3. Bước 3: Plan competing probes

Ignis lập collection plan vừa đủ để phân biệt core, alternative và null hypothesis. Plan nêu rõ required/optional channels, query families, exclusions, sample/window, auth tier, quota và expected evidence role. User chỉ cần xác nhận những boundary có tác động quyền, chi phí hoặc scope; phần sequencing bên trong do agent tự chủ.

### 10.4. Bước 4: Collect and preserve

Connectors thu observation trực tiếp, giữ canonical source identity, source URL, observed/published time nếu có, query, connector revision và collection path. Connector status được ghi theo từng surface, không gộp TikTok search với TikTok comments hoặc Threads API với browser tier.

### 10.5. Bước 5: Qualify

Evidence được đánh giá theo exact mission/Brief revision. Literal keyword match không đủ. Qualification phân biệt:

- qualified support;
- qualified contradiction;
- context only;
- excluded / irrelevant;
- unassessed;
- healthy measured absence.

Coverage, freshness, creator/source diversity, question relevance và missingness được báo riêng. Composite confidence không được che việc relevance thấp hoặc required channel thất bại.

### 10.6. Bước 6: Decide whether analysis is allowed

Sufficiency gate quyết định loại inference được phép. Gate chạy trước narrative generation. Nếu Market evidence chưa đạt ngưỡng tối thiểu, Ignis không phát Opportunity Index, whitespace, saturated segment hay demand-gap verdict.

### 10.7. Bước 7: Analyze and challenge

Senior Market Analytics skill chạy source lenses và cross-source synthesis, nhưng bắt buộc trả lời cả bốn câu:

1. Evidence nào ủng hộ core hypothesis?
2. Evidence nào chống lại nó?
3. Cách giải thích cạnh tranh nào vẫn phù hợp với dữ liệu?
4. Evidence nào sẽ làm recommendation thay đổi?

### 10.8. Bước 8: Deliver and stop

Ignis tạo response, report hoặc dashboard theo user intent; lưu claim ledger và artifact input digest; sau đó kết thúc mission. Nếu cần probe mới, đó là một explicit continuation của mission hoặc một mission revision, không phải background behaviour.

## 11. Evidence contract

### 11.1. Mission manifest tối thiểu

| Field | Ý nghĩa |
|---|---|
| `business_question` | Câu hỏi cần trả lời |
| `decision_context` | Ai quyết định, quyết định gì, chi phí sai |
| `surface` | `ATTENTION`, `MARKET` hoặc tactical collect |
| `target_user` / `problem` | Đối tượng và vấn đề của Market Brief |
| `core_hypothesis` | Mệnh đề chính có thể bị bác bỏ |
| `alternative_hypotheses` | Các giải thích cạnh tranh |
| `null_hypothesis` | Khả năng không có signal đáng kể |
| `falsifiers` / `kill_criteria` | Evidence khiến hypothesis yếu đi hoặc dừng |
| `scope` | Geo, audience, language, timeframe |
| `required_channels` | Kênh thiếu sẽ chặn hoặc giới hạn verdict |
| `optional_channels` | Kênh thiếu chỉ làm giảm coverage |
| `queries` | Root terms, expansions, exclusions, version |
| `collection_window` | Thời gian ingress thực tế |
| `connector_revisions` | Connector version và auth tier |
| `quality_thresholds` | Qualification và sufficiency policy |
| `observations_digest` | Identity của corpus được phân tích |
| `analysis_policy` | Loại inference/output được phép |

### 11.2. Channel states

Mỗi connector surface có một state rõ:

- `HEALTHY`
- `EMPTY_NO_DATA`
- `AUTH_REQUIRED`
- `RATE_LIMITED`
- `DEGRADED`
- `FAILED`
- `NOT_REQUESTED`

`EMPTY_NO_DATA` chỉ hợp lệ khi connector thực sự đo đúng query, scope và timeframe đã khai báo. `AUTH_REQUIRED`, `RATE_LIMITED`, `FAILED` và `NOT_REQUESTED` không bao giờ được diễn giải thành zero.

### 11.3. Claim contract

Mỗi claim trong report phải có:

- claim type và exact wording;
- evidence IDs được dùng;
- evidence role: support, contradiction hay context;
- source/channel distribution;
- inference method;
- confidence và limitation;
- corpus digest và Brief revision;
- điều kiện làm claim thay đổi.

Một claim không bind được vào qualified evidence thì phải được hạ thành assumption, open question hoặc recommendation proposal.

### 11.4. Opportunity Index

Opportunity Index chỉ là output có điều kiện của Market surface, không phải product truth. Khi được phép tính, nó phải đi kèm:

- số observation hợp lệ và bị loại;
- demand/supply denominator;
- trạng thái required channels;
- missing-metric rate;
- phân biệt zero, unknown và not collected;
- sensitivity khi bỏ một source hoặc thay trọng số;
- explanation bằng evidence cụ thể.

Nếu những điều kiện đó chưa có, UI không hiển thị score bị làm mờ hoặc score kèm dấu sao; UI không hiển thị score.

## 12. Senior Market Analytics method

Skill phân tích cung cấp method và template, không cưỡng ép mọi request chạy cùng một pipeline. Với strategic dossier, method tham chiếu gồm:

1. **Outcome frame:** quyết định, stakeholder, hypothesis, falsifier và cost of error.
2. **Demand lens:** search intent, problem expression, behavioural evidence và velocity.
3. **Supply lens:** existing solutions, content/tutorial maturity, competitor presence và measured absence.
4. **Voice of Customer lens:** pain, workaround, objection, willingness signals và language thật.
5. **Context lens:** macro/news/seasonality chỉ làm context trừ khi independently qualify cho Market Brief.
6. **Cross-source synthesis:** convergence, divergence, alternative explanations và sensitivity.
7. **Decision options:** proceed, narrow, reposition, collect more evidence hoặc stop — kèm ai trả chi phí của từng lựa chọn.
8. **Fast validation:** phép thử 3–7 ngày nhắm vào uncertainty lớn nhất, không nhắm vào việc tạo thêm output.

Các tactical request có thể chỉ chạy một lens. Deliverable phải phù hợp với user intent; không ép mọi câu hỏi nhỏ phải nhận một dossier đầy đủ.

## 13. Report và dashboard contract

Một strategic artifact nên có cấu trúc mặc định sau, nhưng được rút gọn theo task:

1. **Decision banner** — câu hỏi, decision owner, hypothesis, scope và corpus digest.
2. **Ingress summary** — từng channel, state, số observation và limitation.
3. **Evidence quality** — relevance, coverage, freshness, diversity, missingness và sufficiency verdict.
4. **Hypothesis scoreboard** — core, alternatives, null; evidence for/against và trạng thái hiện tại.
5. **Source lenses** — demand, supply, VoC và context với inline evidence.
6. **Contradiction register** — signal xung đột, bất thường và interpretation chưa giải quyết.
7. **Market conclusions** — chỉ những claim qua gate; mỗi claim mở được evidence bundle.
8. **Decision options** — trade-off, risk và người trả chi phí.
9. **What would change the verdict** — evidence hoặc threshold có thể đảo kết luận.
10. **Next validation** — probe nhỏ nhất để giảm uncertainty lớn nhất.

Dashboard không được đặt score tổng hợp ở vị trí làm mất context. Trạng thái evidence và channel phải xuất hiện trước Opportunity Index. Màu sắc không được biến unknown thành red/zero. Artifact dùng FINOLABS design system, nhưng visual polish không được che source count, denominator hoặc limitation.

## 14. UX principles

### Outcome-first, không tool-first

Entry point hỏi user đang muốn biết hoặc quyết định gì. Connector selection xuất hiện sau khi scope đã rõ. Với tactical collect đã chỉ định source cụ thể, Ignis thực hiện ngay và chỉ bổ sung câu hỏi khi thiếu boundary có ảnh hưởng thật.

### Progressive disclosure

User thấy verdict, confidence và limitation trước; có thể drill xuống claim → evidence bundle → raw observation → collection manifest. Không bắt user đọc log để audit, nhưng cũng không giấu log sau một score.

### Friction đúng chỗ

Ignis giảm friction ở integration và evidence bookkeeping, nhưng giữ friction ở các điểm không nên tự động hóa mù quáng: xác nhận Market Brief, cấp browser session/token, thay đổi scope, dùng dữ liệu nhạy cảm và phát hành artifact ra ngoài.

### Symmetric challenge

UI không dùng ngôn ngữ khiến supporting evidence trông “chính” còn contradicting evidence trông như ngoại lệ. Cả hai phải có cùng mức prominence, source traceability và quality check.

### Actionable uncertainty

`INSUFFICIENT_EVIDENCE` là một product state bình thường, không phải lỗi. Nó phải đi kèm reason code và next-best probe. `FAILED` chỉ dùng khi hệ thống không hoàn tất được contract vận hành.

## 15. MVP scope

### Trong MVP

- On-demand mission creation và bounded autonomy.
- `ATTENTION` on-demand và `MARKET` hypothesis-driven; không scheduled discovery.
- Market Brief immutable với decision, target user, problem, geo, timeframe, hypothesis và falsifiers.
- Hypothesis Register có alternatives, null hypothesis và kill criteria.
- Connector capability resolution cùng explicit auth/session boundary.
- Mission manifest, per-surface channel states và raw observation provenance.
- Question-relevance qualification; supporting, contradicting, contextual, excluded và unassessed roles.
- Evidence sufficiency gate cùng fail-closed Market verdict.
- Claim-to-evidence ledger và corpus digest.
- `ignis-collect` skill/tool packaging.
- `ignis-analyze` Senior Market Analytics skill và một strategic report template.
- Actionable gap report.
- Benchmark suite cho sufficient, auth-blocked, low-relevance, contradictory và missing-metric missions.

### Ngoài MVP

- Always-on worker, Daily Auto Collect, discovery digest hoặc alerting.
- Enterprise crisis monitoring và guaranteed historical coverage.
- Import arbitrary dataset để tạo primary market evidence.
- Auto-post, engagement hoặc account action trên social.
- Marketplace connector count như mục tiêu sản phẩm.
- Proprietary market-size database.
- Team billing, hosted multi-tenancy hoặc enterprise compliance package.
- Một threshold/weighting framework áp cho mọi vertical.

## 16. Success measurement

Product Mindset yêu cầu tách engineering output khỏi user outcome. Vì đây là product direction mới, chưa có baseline đáng tin cho adoption, willingness-to-pay hoặc decision improvement. Vòng đầu dùng success criteria khám phá; nó tạo baseline cho vòng sau.

### 16.1. Non-negotiable integrity metrics

Các metric này là contract, không phải vanity KPI:

- **Unsupported verdict escape rate:** 0% trên semantic negative controls và insufficient-evidence benchmark.
- **Claim traceability:** 100% strategic claim truy được về qualified evidence hoặc qualified measured absence trong cùng Brief revision.
- **Missingness integrity:** 100% `AUTH_REQUIRED`, `RATE_LIMITED`, `FAILED`, `NOT_REQUESTED` không bị biến thành zero.
- **Counterevidence preservation:** 100% qualified contradictory evidence được giữ và hiển thị trong artifact.
- **Cold/warm collection parity:** cùng persisted config và mission input phải resolve cùng eligible surfaces/vocabulary.
- **Artifact reproducibility:** artifact ghi exact corpus digest, Brief revision và analysis policy đã dùng.

### 16.2. Product outcome metrics cần tạo baseline

- Thời gian từ business question đến **qualified evidence frame**, không phải đến first answer.
- Analyst time tiết kiệm ở collection, provenance và report assembly.
- Tỷ lệ mission tạo ra một next action rõ: proceed, narrow, reposition, collect more hoặc stop.
- Tỷ lệ user có thể chỉ ra evidence chính và counterevidence sau khi đọc report.
- Tỷ lệ mission mà finding làm user thay đổi confidence, problem framing hoặc validation plan.
- Repeat use cho một quyết định mới, không phải số report được export.
- Preference so với generic deep research trong những mission cần social-native evidence governance.

### 16.3. Pilot success criteria

Pilot tối thiểu gồm năm mission thật, tương ứng năm stress case đã xác định trong deep research:

1. đủ evidence đa kênh;
2. một required channel cần auth;
3. volume cao nhưng relevance thấp;
4. signal mâu thuẫn;
5. thiếu metric quan trọng.

Pilot chỉ đạt yêu cầu nếu integrity metrics giữ nguyên trên cả năm case và gap report giúp user nêu được hành động tiếp theo. Adoption, time-saving và willingness-to-pay được đo để tạo baseline; không đặt target chủ quan trước vòng đầu.

## 17. Competitive benchmark

Ignis không benchmark “report nào nghe hay hơn”. Benchmark so với Perplexity, một general deep-research agent và một composable OSS stack trên:

| Dimension | Câu hỏi kiểm tra |
|---|---|
| Evidence completeness | Required source nào đã/không được đo? |
| Gap detection | Hệ thống có phát hiện channel failure và missing denominator không? |
| Claim traceability | Claim có trace đến observation và exact evidence frame không? |
| Counterevidence | Hệ thống có tìm và giữ evidence trái giả thuyết không? |
| Reproducibility | Có manifest, corpus digest và policy đủ để audit không? |
| Refusal correctness | Khi nào hệ thống giữ lại verdict, có đúng không? |
| Analyst effort | Bao nhiêu thời gian phải làm thủ công để đạt cùng mức auditability? |
| Decision usefulness | Output làm rõ lựa chọn và uncertainty nào? |

Perplexity vừa là competitor ở generic synthesis, vừa là substitute khi user không cần social evidence governance, vừa là complement/distribution host khi gọi Ignis qua MCP. Tài liệu Agent API hiện công khai connector semantics, trong đó connector error có thể được đưa in-band để run tiếp tục. Đây là đối chiếu kiến trúc quan trọng cho fail-closed design của Ignis ([Perplexity Agent API Connectors](https://docs.perplexity.ai/docs/agent-api/tools/connectors)).

## 18. Go-to-market hypothesis

### 18.1. Distribution

Ignis không cần thắng cuộc đua standalone chat UI. Distribution ưu tiên skills và MCP để chạy trong nơi analyst đã làm việc: Codex, Claude, Perplexity hoặc host agent khác. Evidence contract phải giữ nguyên bất kể host nào viết narrative.

### 18.2. Proof before promotion

GTM asset đầu tiên không phải một landing-page claim, mà là bộ case study và benchmark công khai cho thấy:

- một mission có đủ evidence và phát verdict;
- một mission bị từ chối đúng;
- một belief phổ biến bị counterevidence làm yếu đi;
- một generic research answer trông hợp lý nhưng thiếu source/channel contract;
- user kiểm tra được claim mà không tin vào Ignis như oracle.

### 18.3. Monetization options sau validation

Core self-hosted tiếp tục open source. Chỉ nên chọn mô hình doanh thu sau khi xác minh willingness-to-pay:

- managed execution/hosting;
- managed connector maintenance và auth diagnostics;
- team evidence workspace, access control và audit export;
- compliance/retention policy packs;
- vertical analytical templates và benchmark datasets có provenance.

Ignis không kiếm tiền bằng cách bán lại opaque social corpus mà product promise đang phản đối.

## 19. Roadmap đề xuất

### Phase 0: Product reset và governance

- Thực thi owner decision ngày 29/09/2026: loại bỏ Always-On Radar, Daily Auto Collect và mọi cơ chế tự khởi động khi không có nhiệm vụ, vì chúng tiêu tốn tài nguyên mà không phục vụ một outcome đang được yêu cầu.
- Ghi ADR thay thế Always-On Radar bằng On-Demand Mission-Bound Ignis.
- Supersede ADR Dual-Track ngày 01/09/2026 và sửa constitution vì Principle I/II hiện vẫn bảo vệ background worker và scheduled ingress.
- Đồng bộ `AGENTS.md`, `CLAUDE.md`, `README.md` và `README.vi.md`; hiện các file này vẫn mô tả worker sweep và daily discovery nên product direction mới đang trực tiếp mâu thuẫn với developer/runtime guidance.
- Triage baseline corpus và scheduled data hiện có: archive read-only khi còn lý do bảo toàn cụ thể; xóa theo quy trình an toàn khi đã xác định không còn giá trị. Không tự động migrate chúng thành mission evidence.
- Lập breaking-removal plan cho scheduler, worker, daily report và MCP tools liên quan; loại bỏ trong breaking release, không duy trì giai đoạn deprecated.
- Rebase backlog: supersede radar-specific work, không tiếp tục tối ưu feed đã bị loại khỏi product direction.

**Exit criterion:** repo có một source of truth thống nhất về target product; không còn tài liệu canonical nào nói hai kiến trúc trái nhau mà không có transition status.

### Phase 1: Evidence control plane

- Mission manifest và channel-state schema.
- Zero/unknown/not-collected/auth-blocked semantics.
- Corpus digest, connector revision và query manifest.
- Question relevance, evidence roles, sufficiency gate và claim ledger.
- Preserve current decision-grade evidence invariants từ Spec 008.

**Exit criterion:** benchmark negative controls không phát unsupported verdict; artifact trace được về exact corpus.

### Phase 2: Hai capability family

- Đóng gói `ignis-collect` với capability map và explicit start/stop.
- Đóng gói `ignis-analyze` với Senior Market Analytics method.
- Bổ sung Hypothesis Register, counterevidence probes và confirmation-risk state.
- Strategic report/dashboard đọc cùng evidence bundle; không có đường bypass gate.

**Exit criterion:** một host agent chạy được end-to-end mission và một tactical collect độc lập mà không cần worker nền.

### Phase 3: Validation benchmark và design partners

- Chạy năm stress-case mission.
- So với Perplexity, general deep research và composable OSS stack.
- Đo analyst time, refusal usefulness, decision change và repeat intent.
- Đánh giá mức độ phù hợp của Vietnam consumer-market beachhead và quyết định giữ nguyên, thu hẹp hay mở rộng sau evidence pilot.

**Exit criterion:** có baseline product outcome và bằng chứng user coi evidence governance là giá trị, không chỉ developer thấy kiến trúc đẹp.

### Phase 4: Distribution và monetization experiment

- Stabilize MCP/skill contracts trên nhiều host.
- Xuất case studies có corpus/claim audit.
- Thử một paid value hypothesis: managed execution, team workspace hoặc connector maintenance.

**Exit criterion:** ít nhất một value hypothesis tạo willingness-to-pay signal mà không vi phạm open-source/evidence promise.

## 20. Risks, counterarguments và mitigation

| Risk / counterargument | Vì sao đáng lo | Mitigation / falsification |
|---|---|---|
| User chỉ cần brief nhanh | Evidence governance có thể là overkill; Perplexity thắng về friction | Đo mission nào user chọn auditability thay vì speed; không ép full dossier cho tactical query |
| Fail-closed gây refusal fatigue | User bỏ sang tool luôn trả lời | Gap report phải actionable; đo tỷ lệ refusal dẫn đến next probe hoặc abandonment |
| Coverage quá hẹp | Không có licensed history/firehose; verdict có thể thiếu đại diện | Chọn wedge có connector đủ; disclose missingness; không claim complete view |
| Confirmation-bias guard thành false balance | Ép mọi claim có hai phía tương đương dù evidence lệch rõ | Tìm phản chứng đối xứng về quy trình, không cân bằng giả tạo về trọng lượng evidence |
| User chọn keyword đã làm corpus lệch | Collection vẫn phục vụ niềm tin ban đầu dù analysis nghiêm | Query expansion từ ngôn ngữ thật, alternative hypothesis probes và sample-frame disclosure |
| Model qualification tự tạo bias mới | Semantic relevance và evidence role vẫn là judgment | Giữ raw observation, reason, confidence; benchmark negative/positive controls; human override có audit trail |
| General agents hấp thụ connectors | Perplexity/Claude có thể gọi cùng data source và viết report tốt hơn | Sở hữu evidence contract, manifest, gate và benchmark; để host trở thành distribution channel |
| “Scientific” tạo false authority | User tin score/model hơn judgment | Không dùng label như bảo chứng; expose method, limitation, sensitivity và unknown |
| Legal/ethical misuse | Public content không đồng nghĩa unrestricted use | Per-connector policy, retention/redaction, explicit session authority và export caveat |
| Existing architecture drift | Repo, vault, constitution và docs đang giữ Always-On model | Phase 0 bắt buộc tạo one source of truth trước product implementation |
| Open source không tạo revenue | Self-hosted core có thể commoditize | Validate paid operational value, không khóa evidence method hoặc bán lại corpus |

## 21. Product decisions và decision points

### Đã được owner xác nhận trong conversation

- **Owner decision ngày 29/09/2026:** bỏ Always-On Radar, Daily Auto Collect, scheduler và daemon tự chạy; Ignis chỉ khởi động khi có nhiệm vụ rõ ràng. Lý do: auto collection tiêu tốn tài nguyên khi chưa có outcome cần phục vụ.
- **Owner decision ngày 29/09/2026:** chọn Vietnam consumer-market research cho founder, operator, analyst và consultant làm beachhead pilot chính thức. Product-market fit vẫn phải được kiểm chứng bằng pilot evidence.
- **Owner decision ngày 29/09/2026:** loại bỏ scheduler, worker, daily-discovery reports và các MCP tools liên quan trong một breaking release; không giữ giai đoạn deprecated.
- **Owner decision ngày 29/09/2026:** baseline corpus và scheduled data không được mặc nhiên chuyển thành mission evidence. Archive read-only nếu còn lý do bảo toàn cụ thể; nếu đã xác định không còn giá trị thì xóa theo quy trình an toàn.
- Ignis tự chủ bên trong nhiệm vụ đã được giao, không tự chủ khi idle.
- Hai capability family: integrated collection skills/connectors và Senior Market Analytics skill/templates.
- Phân tích dựa trên social evidence được Ignis thu thập/verify, không dựa trên opaque purchased datasets.
- Chống confirmation bias là product purpose, không chỉ là report guideline.
- Outcome Thinking, Design Thinking và Critical Thinking là ba product principles nền.

### Proposal recommendation, chưa phải owner decision

- Category: evidence-grounded / evidence-gated social market research agent.
- Tagline: “Own the evidence. Challenge the inference.”
- MVP boundary và roadmap Phase 0–4.
- Monetization chỉ được thử sau khi evidence-governance value được xác minh.

### Owner decision còn cần chốt trước implementation

1. `evidence-gated` hay `evidence-grounded` là category term công khai; proposal dùng `evidence-grounded` cho promise và `evidence-gated` cho cơ chế.

## 22. Acceptance criteria cho proposal

Proposal được owner chấp nhận khi owner có thể trả lời rõ:

- Ignis phục vụ ai trước và từ chối phục vụ use case nào?
- Vì sao Ignis không phải Perplexity for social hoặc open-source Brandwatch?
- Bằng chứng nào tạo ra một strategic verdict hợp lệ?
- Confirmation bias được chặn bằng product behaviour nào?
- Autonomy bắt đầu và kết thúc ở đâu?
- Hai capability family dùng chung contract gì?
- Phase 0 phải xóa mâu thuẫn canonical nào trước khi code tiếp?

Sau khi proposal được duyệt, bước tiếp theo là ghi product decision/ADR, sửa constitution theo decision mới, rồi dùng Spec Kit tạo feature specification cho **On-Demand Mission-Bound Ignis**. Proposal này không tự cấp quyền sửa runtime, migration, MCP signature, version hoặc release.

## 23. Evidence references

Các nguồn dưới đây là tập rút gọn phục vụ trực tiếp cho product proposal. Full bibliography và claim/evidence ledgers nằm trong research archive ngày 29/09/2026.

### Competitors và substitutes

- [TrendScope — Universal trend intelligence](https://github.com/mamboyepez17/trendscope)
- [Radar Intelligence — Open-source media intelligence](https://github.com/Scognamiglio1969/radar-intelligence)
- [Jev Social](https://github.com/socai-io/jev-social)
- [socai](https://github.com/socai-io/socai)
- [4CAT](https://github.com/digitalmethodsinitiative/4cat)
- [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer)
- [GPT Researcher](https://github.com/assafelovic/gpt-researcher)
- [Open Deep Research](https://github.com/langchain-ai/open_deep_research)
- [Perplexity Deep Research](https://www.perplexity.ai/en-GB/hub/products/deep-research)
- [Perplexity Computer](https://www.perplexity.ai/en-GB/products/computer)
- [Perplexity Agent API Connectors](https://docs.perplexity.ai/docs/agent-api/tools/connectors)

### Commercial/data category boundaries

- [Brandwatch Consumer Research](https://www.brandwatch.com/products/consumer-research/)
- [Sprinklr Social Listening](https://www.sprinklr.com/products/consumer-intelligence/social-listening/)
- [Talkwalker Social Listening](https://www.talkwalker.com/products/social-listening)
- [Bright Data Web Scraper API](https://brightdata.com/pricing/web-scraper)
- [Apify Dataset documentation](https://docs.apify.com/storage/dataset)

### Research integrity

- [Disclosure Standards for Social Media and Generative AI Research](https://journals.sagepub.com/doi/10.1177/20563051231216947)
- [FAIR Principles](https://www.go-fair.org/wp-content/uploads/2022/01/FAIRPrinciples_overview.pdf)
- [Ten Simple Rules for Responsible Big Data Research](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1005399)
- [Tow Center — AI Search Has a Citation Problem](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php)
- [The attribution crisis in LLM search results](https://www.cambridge.org/core/journals/data-and-policy/article/attribution-crisis-in-llm-search-results-estimating-ecosystem-exploitation/170DD0B88E5F5AEA8F69F2E9AF1328E3)

## Appendix A: Product Mindset Canvas cho Ignis

### B1. Outcome

Để founder, operator, analyst và consultant có thể ra quyết định market opportunity với mức hiểu biết rõ về evidence và uncertainty, Ignis phải giảm thời gian tạo qualified evidence frame và giảm unsupported verdict. Vì đây là capability mới, vòng pilot dùng success criteria khám phá thay vì bịa baseline/target adoption.

### B2. Design

- **Empathize:** quan sát workflow research hiện tại, thời gian thu thập, cách user giữ link và bảo vệ claim.
- **Define:** làm thế nào để user tự nghe social và phản biện hypothesis mà không phải tự ghép một research stack?
- **Ideate:** open-source Brandwatch; Perplexity for social; evidence-gated research instrument.
- **Prototype:** mission manifest + five-case benchmark + one report template, chưa cần hosted product.
- **Test:** so với generic deep research và composable OSS stack trên evidence integrity và decision usefulness.

### B3. Critical

- **Assumption:** user coi custody, counterevidence và auditability là giá trị đủ lớn để chấp nhận thêm friction.
- **Evidence hiện có:** competitive gap tồn tại ở integrated evidence contract; chưa có primary customer evidence về willingness-to-pay.
- **Root risk:** nếu user chỉ cần brief nhanh, product differentiation không chuyển thành adoption.

### B4. Loop

- Nếu assumption sai, Ignis nên thu hẹp thành evidence service cho analyst/agent host thay vì end-user research product.
- Cách nhanh nhất để biết: chạy năm mission với design partners, quan sát lúc nào họ chọn Ignis thay vì Perplexity và willingness-to-pay nằm ở method, hosting hay connector operations.
