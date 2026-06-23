PHẦN 1: PHÂN HỆ TÀI KHOẢN & XÁC THỰC (AUTHENTICATION & PROFILE)

1. Register (Đăng ký tài khoản)

Bước 1: Guest nhập thông tin (Email, Password, Full Name) trên form đăng ký.

Bước 2: System kiểm tra Email đã tồn tại trong Database (table users) hay chưa. Nếu đã tồn tại, trả về lỗi "Email đã được sử dụng".

Bước 3: Nếu hợp lệ, System mã hóa (hash) mật khẩu và tạo tài khoản mới với status = 'inactive' và gán mặc định plan_id là gói FREE.

Bước 4: System tự động sinh mã OTP (hoặc mã kích hoạt), lưu vào bộ nhớ tạm (Redis/DB) kèm thời gian hết hạn và gửi qua Email cho Guest.

2. Verify by Email (Xác thực tài khoản)

Bước 1: Guest nhập mã OTP từ Email vào giao diện hoặc click vào link xác thực.

Bước 2: System kiểm tra tính chính xác và thời gian sống (expire time) của mã OTP.

Bước 3: Nếu mã hợp lệ, System cập nhật status = 'active' cho User trong table users. Guest chính thức trở thành User và có thể đăng nhập.

3. Login (Đăng nhập)

Bước 1: User nhập Email và Password, hoặc chọn "Đăng nhập bằng Google" (Google OAuth2).

Bước 2: * Nếu đăng nhập thông thường: System kiểm tra Email, so sánh Hash Password trong DB.

Nếu đăng nhập Google: System xác thực ID Token từ Google, check google_id. Nếu User chưa từng có tài khoản, System tự động tạo tài khoản mới với status = 'active' và plan_id gói FREE.

Bước 3: System kiểm tra status của tài khoản. Nếu trạng thái là 'banned', chặn đăng nhập và báo lỗi.

Bước 4: Nếu hợp lệ, System tạo ra một Access Token (JWT) chứa thông tin User ID, Role và trả về cho Client lưu trữ để thiết lập phiên làm việc.

4. Logout (Đăng xuất)

Bước 1: User nhấn nút Đăng xuất trên giao diện.

Bước 2: Client xóa JWT đang lưu trữ. Đồng thời, Client gửi request lên Server để thêm Token đó vào Blacklist (lưu ở Redis) nhằm vô hiệu hóa Token ngay lập tức, đảm bảo bảo mật.

Bước 3: Chuyển hướng người dùng về Landing Page.

5. Forgot Password (Quên mật khẩu)

Bước 1: User nhập Email cần khôi phục mật khẩu tại màn hình "Quên mật khẩu".

Bước 2: System kiểm tra Email có tồn tại không. Nếu có, tạo ra một Token đặt lại mật khẩu tạm thời và gửi Link reset qua Email cho User.

Bước 3: User click vào Link trong Email, tiến hành nhập Mật khẩu mới trên giao diện.

Bước 4: System validate mật khẩu mới, tiến hành hash và cập nhật vào trường password_hash của User trong DB, thông báo thành công và điều hướng về trang Login.

6. Edit Profile (Chỉnh sửa hồ sơ)

Bước 1: User truy cập vào trang Cá nhân, thay đổi thông tin (full_name, tải lên avatar_url mới).

Bước 2: System validate dữ liệu (định dạng ảnh, kích thước file, độ dài chuỗi tên). Tải ảnh lên Cloud Storage để lấy URL nếu user thay avatar.

Bước 3: Cập nhật các trường tương ứng trong table users và trả về thông tin mới cập nhật cho Client hiển thị.

PHẦN 2: PHÂN HỆ QUẢN LÝ TÀI LIỆU (DOCUMENT MANAGEMENT)

7. Upload Document (Tải tài liệu lên)

Bước 1: User chọn file cần tải lên (.pdf, .docx, .txt, .md) và chọn quyền riêng tư (Private hoặc Public).

Bước 2: System kiểm tra status của User. Nếu status == 'overlimitstorage', System lập tức chặn và hiển thị popup yêu cầu xóa bớt tài liệu hoặc gia hạn gói cước.

Bước 3: System lấy thông tin storage_limit của gói cước hiện tại (từ table storage_plans dựa trên plan_id của user). Kiểm tra nếu: storage_used (hiện tại) + file_size_bytes (file mới) > storage_limit -> Chặn upload, thông báo "Dung lượng đầy".

Bước 4: Nếu thỏa mãn dung lượng, System đẩy file lên AWS S3, trích xuất text phục vụ Full-text Search.

Bước 5: Tạo một bản ghi mới vào table documents với trạng thái ban đầu:

Nếu User chọn Private -> status = 'private'.

Nếu User chọn Public -> status = 'pending' (Chờ Admin kiểm duyệt).

Bước 6: Cập nhật cộng dồn dung lượng file mới vào trường storage_used của User trong table users.

8. Document Tagging (Gán nhãn tài liệu)

Bước 1: Khi upload hoặc chỉnh sửa tài liệu, User chọn các tag có sẵn hoặc tự gõ nhãn mới (label).

Bước 2: System kiểm tra nhãn mới đã tồn tại trong table tags chưa. Nếu chưa thì tạo mới bản ghi vào table tags.

Bước 3: System ghi nhận các mối quan hệ giữa tài liệu và nhãn vào table document_tags (document_id, tag_id).

9. Manage Personal Documents (Quản lý tài liệu cá nhân)

Bước 1: User truy cập mục "Tài liệu của tôi" (My Documents).

Bước 2: System kiểm tra trạng thái User, nếu status == 'overlimitstorage' $\rightarrow$ Khóa quyền xem danh sách này, hiển thị màn hình cảnh báo vượt hạn mức.

Bước 3: Nếu trạng thái bình thường, System truy vấn table documents theo uploader_id = current_user_id (Lọc bỏ các file có deleted_at IS NOT NULL).

Bước 4: Trả về danh sách tài liệu kèm trạng thái chi tiết của từng file (private, pending, public, rejected) để render lên giao diện.

10. View & Download Document (Xem và Tải tài liệu)

Bước 1: User hoặc Guest click chọn một tài liệu.

Bước 2: System kiểm tra quyền truy cập:

Nếu file ở trạng thái public: Cho phép tất cả mọi người xem. Nma nếu click nút "Tải về (Download)", System check nếu là Guest thì hiển thị popup yêu cầu Login; nếu là User thì cho tải file trực tiếp từ AWS S3 URL.

Nếu file ở trạng thái private/pending/rejected: Chỉ cho phép chính chủ (uploader_id == current_user_id) hoặc Admin xem preview nội dung.

Bước 3: Hệ thống render và hiển thị trực tiếp nội dung văn bản (PDF, Word) lên trình duyệt (Web Preview).

11. Search Document (Tìm kiếm nâng cao)

Bước 1: Người dùng nhập từ khóa (Keyword) vào thanh tìm kiếm chung trên hệ thống.

Bước 2: System thực hiện Full-text Search dưới Database (hoặc qua Vector/Search Engine) quét theo: Tiêu đề, Nội dung bên trong tài liệu, và các thẻ Tag liên quan.

Bước 3: Hệ thống chỉ trả về các tài liệu thỏa mãn điều kiện status = 'public' và deleted_at IS NOT NULL.

12. Share Document (Chia sẻ link tài liệu)

Bước 1: User bấm nút "Chia sẻ" trên một tài liệu cá nhân của mình.

Bước 2: System tự động sinh ra một mã Hash/UUID duy nhất liên kết với file và cập nhật vào trường link_share trong table documents.

Bước 3: Trả về một URL hoàn chỉnh (ví dụ: aistudyhub.com/shared/document-uuid). Người nhận được link này chỉ có quyền xem nội dung (Read-only) dựa theo cấu hình chia sẻ.

13. Edit Document (Chỉnh sửa thông tin tài liệu)

Bước 1: User bấm nút Chỉnh sửa trên một tài liệu do mình sở hữu.

Bước 2: User tiến hành đổi tên (title), cập nhật thẻ Tags, hoặc thay đổi quyền riêng tư (Private -> Public).

Bước 3: System cập nhật dữ liệu mới vào DB.

Đặc biệt: Nếu User chuyển trạng thái từ Private sang Public, System tự động cập nhật trường status = 'pending' để đẩy vào hàng đợi kiểm duyệt của Admin.

14. Delete Document (Xóa tài liệu - Soft Delete)

Bước 1: User chọn lệnh "Xóa" trên một tài liệu tại trang quản lý cá nhân.

Bước 2: Hệ thống hiển thị Popup xác nhận để đảm bảo User không bấm nhầm.

Bước 3: Khi User xác nhận, System tiến hành Xóa mềm (Soft Delete) bằng cách cập nhật thời gian hiện tại vào trường deleted_at và đổi status = 'deleted' trong table documents. (Giúp ẩn file khỏi giao diện hiển thị ngay lập tức).

Bước 4: System tính toán lại dung lượng: Lấy dung lượng hiện tại của User (storage_used) trừ đi dung lượng file vừa xóa (file_size_bytes) và cập nhật lại vào table users nhằm giải phóng ngay bộ nhớ hạn mức cho User.

(Lưu ý: File vật lý trên S3 có thể được xóa sau bởi một Background Job định kỳ dựa vào trường deleted_at).

PHẦN 3: PHÂN HỆ MỞ RỘNG - SOCIAL LEARNING (TƯƠNG TÁC CỘNG ĐỒNG)

15. Review & Rate Document (Đánh giá tài liệu)

Bước 1: User (đã login) truy cập vào một tài liệu công khai (Public).

Bước 2: User chọn số sao đánh giá (1-5 sao) và nhập nội dung bình luận (comment), sau đó bấm Gửi.

Bước 3: System validate thông tin và tạo một bản ghi mới vào table reviews (user_id, document_id, rating, comment). Tính toán lại điểm trung bình của tài liệu để đưa vào thuật toán gợi ý Trending.

16. Report Document (Báo cáo vi phạm)

Bước 1: User phát hiện một tài liệu công khai chứa nội dung cấm, đề thi mật hoặc từ ngữ không phù hợp, bấm nút "Báo cáo vi phạm".

Bước 2: User nhập lý do báo cáo (reason) và gửi lên hệ thống.

Bước 3: System tạo bản ghi vào table reports với thông tin người báo cáo, mã tài liệu và trạng thái mặc định status = 'pending', đồng thời gửi tín hiệu cảnh báo đến trang quản trị của Admin.

PHẦN 4: PHÂN HỆ AI CHATBOT (RAG ARCHITECTURE)

17. AI Chatbot in My Documents (Truy vấn theo nhóm tài liệu)

Bước 1: User truy cập trang My Documents, tích chọn một hoặc nhiều tài liệu cụ thể làm tập dữ liệu nền (Context Window), sau đó nhập câu hỏi vào khung chat.

Bước 2: [AI Guard Middleware] Backend kiểm tra hạn ngạch của User: Lấy ngày hiện tại so sánh với last_request_date.

Nếu trùng ngày, check ai_requests_today >= max_ai_requests_per_day của gói cước -> Chặn request, báo lỗi vượt hạn mức, yêu cầu nâng cấp gói.

Bước 3: Nếu hạn mức hợp lệ, System kiểm tra xem Session Chat hiện tại đã tồn tại chưa, nếu chưa thì tạo Session mới trong chat_sessions và lưu danh sách tài liệu được chọn vào table session_documents.

Bước 4: System gửi câu hỏi sang ChatbotService. Hệ thống vector hóa câu hỏi, thực hiện kỹ thuật RAG để tìm kiếm các phân đoạn văn bản liên quan nhất chỉ trong phạm vi các tài liệu đã được chỉ định ở bước 1.

Bước 5: LLM tổng hợp câu trả lời kèm thông tin trích dẫn (Tên file, số trang, đoạn văn bản gốc).

Bước 6: System lưu câu hỏi của User và câu trả lời của Bot vào table chat_messages (Trích dẫn được lưu vào trường citations dạng jsonb).

Bước 7: Cập nhật hạn ngạch User trong table users: ai_requests_today = ai_requests_today + 1 và gán last_request_date = current_date. Trả phản hồi về cho giao diện Client.

18. AI Chatbot in View Document (Hỏi đáp & Tóm tắt 1 tài liệu lẻ)

Bước 1: User đang mở xem trực tiếp 1 tài liệu cụ thể và nhập câu hỏi (ví dụ: "Tóm tắt tài liệu này cho tôi").

Bước 2: [AI Guard Middleware] Kiểm tra hạn quota ngày ai_requests_today tương tự như Luồng 17, nếu quá hạn mức thì chặn.

Bước 3: Hệ thống gửi yêu cầu qua ChatbotService để xử lý RAG, nma giới hạn phạm vi truy xuất thông tin độc nhất trong đúng ID của tài liệu đang xem.

Bước 4: LLM sinh câu trả lời tóm tắt/đáp án kèm nguồn dẫn chứng cụ thể.

Bước 5: Lưu tin nhắn vào DB, tăng biến đếm ai_requests_today lên 1 và cập nhật thời gian last_request_date. Trả kết quả về giao diện chat.

19. Manage Chat History (Quản lý lịch sử Chat)

Bước 1: User bấm vào mục Lịch sử trò chuyện (Chat History).

Bước 2: System query table chat_sessions lọc theo user_id = current_user_id và hiển thị danh mục các cuộc trò chuyện cũ (Lọc các session có deleted_at IS NULL).

Bước 3: Khi User click vào một session cụ thể, System lấy toàn bộ danh sách các tin nhắn liên quan từ table chat_messages sắp xếp theo thời gian created_at tăng dần để hiển thị lại toàn bộ nội dung trò chuyện cũ cho User.

Lưu ý: User có quyền thực hiện đổi tên tiêu đề cuộc trò chuyện (title) hoặc chọn Xóa cuộc trò chuyện (Cập nhật trường deleted_at của session).

PHẦN 5: PHÂN HỆ QUẢN TRỊ VIÊN (ADMIN DASHBOARD)

20. Approve/Reject Public Document (Duyệt tài liệu Public)

Bước 1: Admin vào trang quản trị, truy cập bộ lọc danh sách tài liệu có trạng thái status = 'pending'.

Bước 2: Admin xem trước nội dung tài liệu, kiểm tra tính hợp lệ.

Bước 3: Admin đưa ra quyết định:

Approve (Duyệt): Đổi status = 'public'. Tài liệu chính thức xuất hiện trên kho tài liệu chung.

Reject (Từ chối): Đổi status = 'rejected'. Tài liệu bị ẩn khỏi kho chung nma vẫn hiển thị trong mục cá nhân của User kèm lý do bị từ chối.

Bước 4: System tự động tạo một bản ghi thông báo vào table notifications để gửi tin nhắn đến tài khoản của User sở hữu tài liệu đó.

21. Handle Document Reports (Xử lý báo cáo vi phạm)

Bước 1: Admin vào mục "Quản lý Báo cáo", xem danh sách các lượt report đang ở trạng thái status = 'pending'.

Bước 2: Admin kiểm tra lý do và tài liệu bị báo cáo để phân xử:

Nếu báo cáo đúng: Đổi trạng thái report thành 'resolved', giáng trạng thái tài liệu về 'rejected' hoặc 'deleted'. Đồng thời ghi nhận 1 lịch sử vi phạm của User tải file lên vào table violation_histories.

Nếu báo cáo sai: Đổi trạng thái report thành 'rejected' (Bác bỏ báo cáo), tài liệu giữ nguyên trạng thái Public.

22. Warn/Ban User (Cảnh cáo hoặc Khóa tài khoản)

Bước 1: Admin vào trang quản lý User, kiểm tra lịch sử vi phạm trong table violation_histories.

Bước 2: Admin thực hiện hành động:

Warn (Cảnh cáo): Gửi một thông báo hệ thống và email nhắc nhở nghiêm túc tới User.

Ban (Khóa tài khoản): Cập nhật trường status = 'banned' tại table users của người dùng đó.

Bước 3: Nếu User bị hành động Ban, hệ thống lập tức thêm các token hiện hành của User này vào Blacklist. User đang thao tác trên Web sẽ ngay lập tức bị kích văng ra màn hình đăng nhập, mọi request tiếp theo sử dụng token cũ đều bị Backend từ chối.

23. View System Statistics (Xem thống kê hệ thống)

Bước 1: Admin nhấn vào màn hình Tổng quan/Thống kê.

Bước 2: System thực hiện các câu lệnh Count/Sum/Group By để tính toán số liệu: Tổng số người dùng mới, Tổng số tài liệu tải lên thành công, Thống kê dung lượng đám mây đã tiêu tốn, và Doanh thu các gói cước theo tháng. Render dữ liệu dạng biểu đồ.

PHẦN 6: PHÂN HỆ THƯƠNG MẠI HÓA & THANH TOÁN (SUBSCRIPTION & PAYMENT)

24. Buy Premium Subscription (Đăng ký/Gia hạn gói cước Premium)

Bước 1: User vào Dashboard gói cước, bấm chọn đăng ký gói "PREMIUM" (Ví dụ: Chu kỳ 30 ngày).

Bước 2: System tạo một bản ghi hóa đơn mới vào table invoices với trạng thái status = 'pending' và lưu thông tin plan_id tương ứng.

Bước 3: Hệ thống gọi API sang cổng thanh toán liên kết (MoMo/VNPay/VietQR), gửi kèm Mã hóa đơn (UUID) để sinh mã QR Code động chứa chính xác số tiền và nội dung chuyển khoản độc nhất. Hiển thị mã QR lên màn hình cho User quét.

25. Payment Automation Processing (Xử lý Webhook thanh toán tự động)

Bước 1: User quét mã QR và thực hiện chuyển tiền thành công trên ứng dụng ngân hàng/ví điện tử.

Bước 2: Cổng thanh toán tự động bắn một request dạng HTTP POST (Webhook Callback) về Endpoint cấu hình sẵn của Backend ứng dụng.

Bước 3: Backend tiếp nhận Webhook, tiến hành kiểm tra chữ ký bảo mật (Checksum/Signature) để đảm bảo dữ liệu không bị giả mạo. Khớp mã giao dịch transaction_id với mã hóa đơn trong DB.

Bước 4: Nếu giao dịch hợp lệ và thành công, System thực hiện một chuỗi hành động mang tính nguyên tử (Database Transaction):

Cập nhật trạng thái hóa đơn: status = 'success' trong table invoices.

Cập nhật thông tin User tại table users: Đổi plan_id thành mã gói Premium, thiết lập ngày hết hạn gói cước plan_expires_at = NOW() + INTERVAL '30 days'. Nếu User đang ở trạng thái 'overlimitstorage', tự động đưa status quay về thành 'active'.

Tạo bản ghi vào table notifications để thông báo cho User biết họ đã nâng cấp gói thành công.

26. Reset hạn ngạch AI hàng ngày (Cơ chế Lazy Update + Redis Counter)

Mô tả: Thay vì chạy Cron Job quét toàn bộ Database vào nửa đêm gây nghẽn hệ thống, hạn mức AI sẽ được quản lý và tự động reset hoàn toàn dựa trên cơ chế bộ nhớ đệm (Cache) tốc độ cao của Redis khi User thực hiện tương tác thực tế.

Các bước thực hiện:

Bước 1: User gửi một Request câu hỏi chat với AI (ở trang My Documents hoặc trang View Document).

Bước 2: [AI Guard Middleware] Hệ thống chặn Request lại để kiểm tra hạn ngạch. Thay vì Query vào Postgres DB, Backend sẽ kiểm tra lượt Request của User trong ngày bằng cách truy vấn một Key trên Redis theo cấu trúc định dạng: user:ai_limit:{user_id}:{yyyy-mm-dd}.

Bước 3: Backend thực hiện lệnh INCR (Increment) lên Key đó trên Redis:

Trường hợp 1 (Request đầu tiên trong ngày mới): Key chưa tồn tại -> Redis tự động khởi tạo Key với giá trị là 1. Ngay lập tức, Backend gọi lệnh EXPIRE để thiết lập thời gian sống (TTL) cho Key này là 24 giờ (hoặc tính toán chính xác số giây còn lại từ thời điểm hiện tại đến 23:59:59 cùng ngày).

Trường hợp 2 (Các request tiếp theo trong ngày): Key đã tồn tại $\rightarrow$ Redis tự động cộng dồn giá trị lên 2, 3, 4... và trả về số đếm hiện tại ngay lập tức.

Bước 4: Backend so sánh số đếm trả về từ Redis với hạn mức tối đa của User (max_ai_requests_per_day lấy từ thông tin gói cước đang lưu trên Token/Session):

Nếu số đếm vượt quá hạn mức -> Chặn đứng Request, không gửi sang API của LLM, trả về thông báo lỗi "Bạn đã hết lượt Chat AI trong ngày hôm nay, vui lòng nâng cấp gói".

Nếu số đếm nằm trong hạn mức -> Cho phép đi tiếp, chuyển tiếp câu hỏi sang cho ChatbotService để xử lý RAG và sinh câu trả lời cho User.

Bước 5 (Đồng bộ ngầm - Optional): Hệ thống có thể chạy một Background Worker định kỳ (vài tiếng một lần hoặc khi User kết thúc Session) để sync số lượng Request từ Redis về trường ai_requests_today trong DB để lưu log thống kê cho Admin, tuyệt đối không gây block luồng chat chính của User.

27. Kiểm tra hết hạn gói cước Subscription (Cơ chế Lazy Downgrade khi User tương tác)

Mô tả: Hệ thống không thực hiện quét đồng loạt cả triệu dòng DB vào ban đêm để hạ cấp gói cước. Thay vào đó, việc kiểm tra và hạ cấp sẽ được kích hoạt "lười biếng" ngay tại thời điểm User có hành động truy cập vào hệ thống, giúp phân tán tải và tiết kiệm tài nguyên CPU cho các tài khoản không hoạt động.

Các bước thực hiện:

Bước 1: User thực hiện một hành động bất kỳ gửi Request lên hệ thống (ví dụ: Đăng nhập lại, F5 tải lại trang Dashboard, hoặc bấm nút Upload một tài liệu mới).

Bước 2: [Subscription Check Middleware] Hệ thống lấy thông tin tài khoản của User từ table users lên và thực hiện một câu lệnh điều kiện kiểm tra nhanh:

if (user.plan_id != 'gói_free' AND user.plan_expires_at < NOW())

Bước 3: Nếu điều kiện trên là ĐÚNG (tức là gói Premium của User đã thực sự quá hạn 30 ngày nma hệ thống chưa xử lý hạ cấp trước đó), Middleware sẽ lập tức kích hoạt quy trình hạ cấp tài khoản tự động (Database Transaction):

Đổi plan_id của User về lại mã của gói FREE.

Đặt lại trường thời gian hết hạn plan_expires_at = NULL.

Bước 4 (Kiểm tra và áp dụng chế độ phạt Over-limit theo F-MON-01): Hệ thống thực hiện đối chiếu dung lượng ngay lập tức: lấy tổng dung lượng đã dùng (storage_used) của User so sánh với hạn mức tối đa (storage_limit) của gói FREE vừa bị giáng xuống.

Trường hợp vượt hạn mức: Nếu storage_used > storage_limit_free -> Hệ thống cập nhật trường trạng thái của User thành status = 'overlimitstorage'.

Trường hợp hợp lệ: Nếu storage_used <= storage_limit_free -> Giữ nguyên trạng thái status = 'active'.

Bước 5: Hệ thống tạo một bản ghi thông báo mới vào table notifications với nội dung: "Gói cước Premium của bạn đã hết hạn và được chuyển về gói Free. [Cảnh báo] Dung lượng lưu trữ của bạn đã vượt quá hạn mức gói Free, vui lòng xóa bớt tài liệu hoặc gia hạn Premium để mở khóa các tính năng".

Bước 6: Middleware hoàn tất xử lý và trả về phản hồi cho giao diện Client. UI/UX của User sẽ lập tức cập nhật giao diện tương ứng với trạng thái tài khoản mới (Khóa nút Upload, khóa quyền vào trang My Documents nếu bị dính trạng thái overlimitstorage).