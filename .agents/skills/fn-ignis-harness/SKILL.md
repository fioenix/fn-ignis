---
name: fn-ignis-harness
description: Autonomous Trend Intelligence & Market Opportunity Agent Harness for deep multi-platform listening, white-space analysis, human-friendly mission tracking, and cross-agent session mapping.
---

# fn-ignis Trend Intelligence & Market Opportunity Agent Harness 🚀

Skill này cung cấp cho AI Agent một khung điều phối nghiên cứu tự động (Agent Harness) với khả năng:
1. **Cross-Agent Session Tracing**: Cho phép gắn `agent` (`claude_desktop`, `claude_code`, `codex`) và `session_id` (`codex://threads/...`, `conversation_id`) vào Mission. Giúp Agent tự động khôi phục ngữ cảnh làm việc khi mở lại phiên chat mà User không cần gõ lại mã!
2. **Human-Friendly Mission Tracking (Shortcode UX)**: Tự động gắn mã định danh ngắn dễ nhớ (`shortcode` như `VN-AI-AGENT-90D` hoặc `FB16C5EE`).
3. **Autonomous Refinement Loop**: Tự động mở rộng từ khóa phụ nếu dữ liệu vòng 1 chưa đủ sâu.
4. **Quality & Integrity Scorecard**: Chấm điểm minh bạch độ tin cậy của dataset (Coverage, Language Precision, Freshness, Creator Diversity).
5. **White Space Discovery (Khoảng trống thị trường)**: Tự động so sánh Nhu cầu tìm kiếm (Google Trends) và Nguồn cung nội dung (YouTube) để tìm cơ hội kinh doanh.
6. **Deterministic Executive Artifacts**: Xuất báo cáo HTML độc lập hoàn chỉnh chuẩn xác 100%.

---

## 🎨 Quy Chuẩn Giao Tiếp & Giao Diện Bắt Buộc

### 1. Banner Nhận Diện Chiến Dịch
Khi bắt đầu hoặc phản hồi bất kỳ kết quả nghiên cứu nào, **Agent PHẢI LUÔN hiển thị banner nhận diện rõ ràng**:

> **🎯 Chiến dịch:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation tại Việt Nam*  
> **Mã tra cứu nhanh:** `VN-AI-AGENT-90D` *(hoặc `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(nếu có)*

### 2. Nguyên Tắc Trình Bày Artifacts (Light Mode First) ☀️
- **BẮT BUỘC:** Ưu tiên sử dụng **Light Mode** (nền trắng/slate-50 sáng, chữ xám đậm/đen tương phản cao, thẻ trắng viền xám tinh tế, badge màu sắc rõ ràng) cho toàn bộ file HTML Artifacts và báo cáo trực quan.
- **CHỈ SỬ DỤNG Dark Mode khi User có yêu cầu cụ thể** (ví dụ: *"hãy đổi sang darkmode"* hoặc *"render dark theme"*).

---

## 🛠️ Danh Mục FastMCP Tools Hỗ Trợ Session Tracking

### 1. `get_current_session_mission(session_id="...")`
- **Mục đích:** Tự động khôi phục Mission của phiên chat hiện tại khi mở lại cuộc trò chuyện mà không cần hỏi User mã mission.

### 2. `run_autonomous_research_mission`
- **Tham số nâng cao:** `topic`, `keywords`, `geo="VN"`, `timeframe="90d"`, `agent="codex" | "claude"`, `session_id="codex://threads/..."`

### 3. `get_mission_analysis` & `generate_mission_artifact`
- **Tham số:** Chấp nhận cả `Shortcode` (`VN-AI-AGENT-90D`), `8-char prefix` (`fb16c5ee`), `UUID`, hoặc chính `SessionID`!
- **Cơ chế:** Tự động ghi file HTML vào thư mục `reports/` và trả về JSON metadata siêu nhẹ để tránh tràn token buffer.
