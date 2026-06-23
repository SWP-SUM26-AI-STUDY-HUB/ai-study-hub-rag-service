# BẢN ĐẶC TẢ YÊU CẦU NGHIỆP VỤ (BUSINESS REQUIREMENT DOCUMENT - BRD)

## DỰ ÁN: HỆ THỐNG QUẢN LÝ TÀI LIỆU HỌC TẬP TÍCH HỢP AI (AI STUDY HUB)

---

## 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)

### 1.1. Bối cảnh (Context)

Trong quá trình học tập tại môi trường đại học, sinh viên thường xuyên đối mặt với tình trạng quá tải thông tin và quản lý dữ liệu kém hiệu quả. Tài liệu học tập (Slide bài giảng, đề thi cũ, tài liệu tham khảo, bài tập lớn) bị phân tán trên nhiều nền tảng cấu trúc khác nhau bao gồm Google Drive, Messenger, Facebook Groups, Email cá nhân và các thiết bị lưu trữ vật lý (USB). Thực trạng này dẫn đến việc thất lạc dữ liệu, tốn thời gian tra cứu và giảm hiệu suất học tập.

### 1.2. Vấn đề cốt lõi (Problem Statements)

- **Dữ liệu phân tán:** Không có kho lưu trữ trung tâm, tài liệu nằm rải rác trên nhiều kênh truyền thông và lưu trữ khác nhau.
- **Hiệu suất tìm kiếm thấp:** Thiếu công cụ phân loại khoa học và cơ chế tìm kiếm thông minh, gây khó khăn khi cần truy xuất lại tài liệu cũ.
- **Quá tải thông tin:** Sinh viên mất nhiều thời gian để đọc và lọc kiến thức cốt lõi từ các tài liệu dài (PDF, Docx).
- **Chia sẻ thủ công:** Quy trình chia sẻ tài liệu giữa các sinh viên, nhóm học tập hoặc các khóa học còn mang tính rời rạc, chưa có tính kế thừa.
- **Giới hạn phần cứng:** Dung lượng lưu trữ trên thiết bị cá nhân bị hạn chế, đòi hỏi một giải pháp lưu trữ đám mây tập trung.

### 1.3. Mục tiêu hệ thống (System Goals)

- Xây dựng nền tảng Web tập trung cho phép quản lý, lưu trữ và phân loại tài liệu học tập theo cấu trúc khoa học.
- Tích hợp công nghệ Trí tuệ nhân tạo (AI Chatbot) dựa trên kiến trúc RAG (Retrieval-Augmented Generation) để hỗ trợ tương tác, hỏi đáp trực tiếp trên nội dung tài liệu.
- Tối ưu hóa quy trình chia sẻ tài liệu trong cộng đồng sinh viên.
- Áp dụng quy trình phát triển phần mềm Fullstack thực tế, đảm bảo tính mở rộng và bảo mật của hệ thống.

---

## 2. ĐỐI TƯỢNG SỬ DỤNG (ACTORS & ROLES)

Hệ thống bao gồm 4 tác nhân chính:

| Tác nhân (Actor)   | Loại tác nhân | Mô tả vai trò                                                                                                                                    |
| :----------------- | :------------ | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Guest**          | Người dùng    | Người dùng chưa xác thực. Chỉ có quyền xem trang giới thiệu (Landing Page), thực hiện đăng ký và đăng nhập hệ thống.                             |
| **User**           | Người dùng    | Sinh viên hoặc người học đã xác thực. Có toàn quyền quản lý tài liệu cá nhân, chia sẻ tài liệu công khai và tương tác với AI Chatbot.            |
| **Admin**          | Người dùng    | Quản trị viên hệ thống. Có quyền quản lý người dùng, kiểm duyệt tài liệu công khai, cấu hình hệ thống và theo dõi log vận hành.                  |
| **ChatbotService** | Hệ thống      | Tác nhân hệ thống (System Actor). Chịu trách nhiệm xử lý ngôn ngữ tự nhiên, vector hóa tài liệu và thực hiện truy vấn RAG để trả lời người dùng. |

---

## 3. YÊU CẦU CHỨC NĂNG CHI TIẾT (FUNCTIONAL REQUIREMENTS)

### 3.1. Phân hệ Xác thực & Tài khoản (Authentication & Profile)

- **F-AUTH-01: Đăng ký tài khoản:** Cho phép người dùng tạo tài khoản mới qua Email. Hỗ trợ xác thực đăng ký thông qua liên kết kích hoạt hoặc mã OTP.
- **F-AUTH-02: Đăng nhập & Đăng xuất:** Xác thực người dùng bằng cơ chế JWT (JSON Web Token) để duy trì phiên làm việc bảo mật. Hỗ trợ Đăng nhập nhanh qua bên thứ ba (Google OAuth2).
- **F-AUTH-03: Khôi phục mật khẩu:** Cung cấp quy trình đặt lại mật khẩu an toàn qua Email khi người dùng sử dụng chức năng quên mật khẩu.
- **F-AUTH-04: Quản lý hồ sơ cá nhân (Profile):** Cho phép thay đổi thông tin cơ bản bao gồm tên hiển thị, ảnh đại diện, mật khẩu.

### 3.2. Phân hệ Quản lý Tài liệu (Document Management)

- **F-DOC-01: Upload tài liệu:** Hỗ trợ tải lên các định dạng file phổ biến bao gồm `.pdf`, `.docx`, `.txt`, `.md`. Áp dụng giới hạn dung lượng tối đa trên mỗi file (ví dụ: 20MB) tùy theo cấu hình phân quyền tài khoản.
- **F-DOC-02: Document Tagging:** Khi tải file lên thì người dùng sẽ chọn các tag có sẵn hoặc là tự tạo ra tag riêng cho mình để hỗ trợ phân loại, quản lí tài liệu.
- **F-DOC-03: Tìm kiếm nâng cao (Advanced Search):** Tích hợp tính năng Full-text Search (Tìm kiếm toàn văn), hỗ trợ truy vấn không chỉ theo tiêu đề file mà còn theo nội dung văn bản bên trong tài liệu.
- **F-DOC-04: Cấu hình quyền riêng tư:** Người dùng có thể thiết lập trạng thái tài liệu:
    - _Cá nhân (Private):_ Chỉ chủ sở hữu mới có quyền xem và sử dụng để chat với AI.
    - _Công khai (Public):_ Chia sẻ lên kho tài liệu chung của hệ thống (Yêu cầu qua bước kiểm duyệt của Admin).

### 3.3. Phân hệ Lưu trữ Đám mây (Cloud Storage)

- **F-STG-01: Lưu trữ phân tán:** Tích hợp với các dịch vụ lưu trữ đám mây tiêu chuẩn (AWS S3) để lưu trữ file tĩnh, tách biệt hoàn toàn với máy chủ ứng dụng.
- **F-STG-02: Xem trước tài liệu (Preview):** Hỗ trợ render và hiển thị trực tiếp nội dung file PDF, Word, PowerPoint trên giao diện Web mà không bắt buộc người dùng phải tải về thiết bị cục bộ.

### 3.4. Phân hệ AI Chatbot (Kiến trúc RAG)

- **F-AI-01: Truy vấn theo ngữ cảnh (Contextual Chat):** Người dùng có thể vào trang My Documents để có nhóm tài liệu cụ thể làm tập dữ liệu nền (Context Window) cho Chatbot. AI chỉ xử lý và trả lời câu hỏi dựa trên phạm vi dữ liệu được chỉ định này.
- **F-AI-02: Truy vấn theo chi tiết Document:** Người dùng chọn một document bất kì và hỏi đáp, yêu cầu AI tóm tắt nội dung của document đó. AI sẽ chỉ xử lí dữ liệu của riêng tài liệu được chỉ định.
- **F-AI-03: Trích dẫn nguồn (Citations):** Phản hồi từ AI phải bao gồm thông tin tham chiếu chính xác (Tên file, số trang, phân đoạn văn bản cụ thể) nguồn gốc của thông tin dữ liệu dùng để tạo câu trả lời, nhằm hạn chế tối đa hiện tượng ảo giác của mô hình (AI Hallucination).
- **F-AI-04: Quản lý phiên hội thoại (Session Management):** Lưu trữ lịch sử trò chuyện theo các phân đoạn hội thoại (Chat Session). Người dùng có quyền xem lại, đổi tên hoặc xóa các phiên hội thoại cũ.

---

## 4. TÍNH NĂNG MỞ RỘNG ĐỀ XUẤT (PROPOSED SYSTEM ENHANCEMENTS)

Nhằm tối ưu hóa trải nghiệm người dùng và nâng cao giá trị thực tế của hệ thống, các tính năng sau được đề xuất tích hợp vào lộ trình phát triển:

- **Hệ thống đánh giá cộng đồng (Social Learning Framework):** Bổ sung cơ chế tương tác giữa các thành viên bao gồm đánh giá số sao (1-5), Bình luận và Báo cáo sai phạm (Report) đối với các tài liệu ở chế độ Công khai. Tài liệu có tương tác tích cực cao sẽ được ưu tiên hiển thị ở danh mục xu hướng (Trending).
---

## 5. Thương mại hóa & Thanh toán (Monetization & Payment)

**F-MON-01: Quản lý và Hiển thị Gói cước (Subscription Dashboard):**

- Hệ thống cung cấp giao diện hiển thị các gói dịch vụ (Free, Premium) kèm thông tin chi tiết về quyền lợi (giới hạn dung lượng lưu trữ, giới hạn AI Request).

- Cho phép người dùng theo dõi Real-time trạng thái tài khoản hiện tại: dung lượng bộ nhớ đã dùng/còn lại, và số lượng lượt Request đã dùng/còn lại trong ngày.

- Số lượng request sẽ được reset sau mỗi ngày và chu kì thanh toán gói cước là 30 ngày. nếu sau 30 ngày mà user không gia hạn thì user sẽ bị hạ từ gói Premium xuống Free.

- Nếu user đang có dung lượng vượt quá ngưỡng cho phép sau khi bị hạ từ PREMIUM xuống Free thì user sẽ bị khoá nút upload, xem tài liệu (My document). user có 2 cách xử lí đó là gia hạn gói premium hoặc là xoá bớt tài liệu của mình sao cho phù hợp với dung lượng của gói Free.

**F-MON-02: Tích hợp Cổng thanh toán (Payment Gateway Integration):**

- Tích hợp các cổng thanh toán trực tuyến phổ biến (MoMo API, VNPay hoặc VietQR) để xử lý giao dịch.

- Hệ thống tự động tạo mã QR Code động kèm theo số tiền và nội dung chuyển khoản chính xác (UUID của giao dịch) để người dùng quét mã nhanh chóng.

**F-MON-03: Xử lý tự động hóa Đăng ký (Subscription Automation via Webhook):**

- Hệ thống triển khai các endpoint Webhook để lắng nghe phản hồi trạng thái giao dịch (Callback) từ phía cổng thanh toán.

- Khi giao dịch thành công, hệ thống tự động cập nhật gói sử dụng của người dùng (ví dụ: từ gói FREE lên gói Premium), đồng thời mở rộng ngay lập tức hạn mức lưu trữ và reset/cấp mới hạn ngạch AI Token.

**F-MON-04: Kiểm soát Hạn mức AI (AI Guard & Rate Limiting):**

- Xây dựng lớp Middleware tại Backend để kiểm tra quyền truy cập và số lượng hạn ngạch (Request) còn lại của tài khoản trước khi chuyển tiếp yêu cầu đến ChatbotService.

- Nếu người dùng vượt quá hạn mức cho phép của gói hiện tại, hệ thống sẽ chặn yêu cầu, kh gửi đến API của LLM để tối ưu chi phí, và trả về thông báo hướng dẫn người dùng nâng cấp gói cước trên giao diện.

**F-MON-05: Lịch sử Giao dịch & Hóa đơn (Transaction History):**

- Lưu trữ toàn bộ lịch sử nâng cấp gói cước của người dùng bao gồm: Mã giao dịch, số tiền, phương thức thanh toán, thời gian, và trạng thái (Thành công/Thất bại/Đang xử lý).
