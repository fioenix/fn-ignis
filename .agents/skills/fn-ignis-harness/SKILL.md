---
name: fn-ignis-harness
description: Autonomous Trend Intelligence & Market Opportunity Agent Harness for deep multi-platform listening, white-space analysis, human-friendly mission tracking, and cross-agent session mapping.
---

# fn-ignis Trend Intelligence & Market Opportunity Agent Harness 🚀

Skill này cung cấp cho AI Agent một khung điều phối nghiên cứu tự động (Agent Harness) với khả năng:
1. **Cross-Agent Session Tracing**: Gắn `agent` và `session_id` (`codex://threads/...`, `conversation_id`) vào Mission. Tự động khôi phục ngữ cảnh làm việc khi mở lại phiên chat.
2. **Human-Friendly Mission Tracking (Shortcode UX)**: Tự động gắn mã định danh ngắn (`FB16C5EE` hoặc `VN-AI-AGENT-90D`).
3. **Quality & Integrity Scorecard**: Chấm điểm minh bạch độ tin cậy của dataset (Coverage, Language Precision, Freshness, Creator Diversity).
4. **White Space Discovery (Khoảng trống thị trường)**: Bóc tách 10 cơ hội thị trường thực tế dựa trên chênh lệch Cung - Cầu.
5. **Claude Native Artifacts First**: Hiển thị kết quả phân tích trực tiếp trên giao diện Chat UI.

---

## 🎨 Quy Chuẩn Hiển Thị Kết Quả Bắt Buộc

### 1. Banner Nhận Diện Chiến Dịch
Khi phản hồi kết quả, **Agent PHẢI LUÔN hiển thị banner nhận diện**:

> **🎯 Chiến dịch:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation tại Việt Nam*  
> **Mã tra cứu nhanh:** `VN-AI-AGENT-90D` *(hoặc `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(nếu có)*

### 2. Quy Tắc Sinh Artifact (Claude Native Artifact First) 🌟
- **MẶC ĐỊNH TRONG CHAT:** Khi người dùng yêu cầu phân tích/báo cáo mission, Agent gọi `get_mission_analysis(mission_id)` và **TỰ ĐỘNG HIỂN THỊ KẾT QUẢ DƯỚI DẠNG CLAUDE NATIVE ARTIFACT** (khung Artifact bên phải màn hình chat).
  - Sử dụng Markdown Infographic / Visual Tables / Badges màu sắc / Light Mode sạch sẽ.
  - Trình bày mạch lạc theo Storyflow 5 phần: *Executive Pulse $\rightarrow$ Scorecard Radar $\rightarrow$ White Space Matrix (10 topics) $\rightarrow$ Strategic Insights & Action Blueprint $\rightarrow$ Top Signals Evidence*.
- **CHỈ XUẤT FILE LOCAL (`reports/`):** Chỉ gọi `generate_mission_artifact` khi người dùng có **yêu cầu xuất/lưu file HTML cụ thể** (ví dụ: *"hãy xuất file HTML ra máy"*, *"lưu báo cáo ra file"*).

---

## 🛠️ Hướng Dẫn Sử Dụng FastMCP Tools

### 1. `get_current_session_mission(session_id="...")`
- Tự động khôi phục Mission của phiên chat hiện tại khi mở lại cuộc trò chuyện.

### 2. `execute_mission_ingress(mission_id="...")`
- Kích hoạt cào dữ liệu đa kênh (Replace Mode, làm sạch rác, lọc theo timeframe).

### 3. `get_mission_analysis(mission_id="...")` (KHUYÊN DÙNG CHO NATIVE ARTIFACT)
- Trả về toàn bộ dữ liệu phân tích chiến lược (Scorecard, 10 White Spaces, Insights, Action Plan, Top Signals) trong payload JSON nhẹ (~3KB) để Agent dựng Claude Native Artifact.

### 4. `generate_mission_artifact(mission_id="...")` (CHỈ DÙNG KHI USER YÊU CẦU XUẤT FILE)
- Render file HTML Infographic Canvas độc lập và lưu vào thư mục `reports/`.
