# Detailed Acceptance Criteria (AC) - AI Study Hub

This document defines the detailed Acceptance Criteria (AC) in the form of Behavior-Driven Development (BDD) Gherkin scenarios for the **AI Study Hub** project. All scenarios are mapped directly from the [Refined Functional Requirements](file:///Users/chithien/code/SWP_Project/functional_requirements.md).

---

## 📌 BDD Gherkin Conventions

Test scenarios are written using standard Gherkin keywords:
- **Given:** The initial state, preconditions, or system context.
- **When:** An action triggered by the user or a system event.
- **Then:** The expected, measurable, and verifiable outcome.
- **And:** A combination of additional conditions or outcomes.

---

## 📑 Subscription Limits Summary Table
For testing edge cases related to permissions and storage limits:

| Feature / Limit | Free Plan (Default) | Premium Plan |
| :--- | :--- | :--- |
| **Max Cloud Storage** | 200 MB | 10 GB |
| **Daily AI Request Limit** | 15 chats/day | 500 chats/day |
| **Allowed File Formats** | `.pdf`, `.docx`, `.txt`, `.md` | `.pdf`, `.docx`, `.txt`, `.md` |
| **Max File Upload Size** | 20 MB | 20 MB |

---

## 🚪 PART 1: AUTHENTICATION & PROFILE (F-AUTH)

### 1. Account Registration (F-AUTH-01)

> [!NOTE]
> Passwords must be hashed using the `bcrypt` algorithm before being saved to the database. The initial account status upon successful registration must be `'inactive'`, and the default plan must be set to `'Free'`.

#### Scenario 1: Successful account registration (Happy Path)
- **Given** The guest is on the Account Registration page.
- **When** The guest enters an email address that does not exist in the system, a valid full name, and a secure password.
- **And** The guest clicks the "Register" button.
- **Then** The system queries the database to verify the email address is not in use.
- **And** The system hashes the password using bcrypt.
- **And** The system creates a new user record in the database with status `'inactive'` and the default plan set to `'Free'`.
- **And** The system generates a secure one-time password (OTP) with an expiration of 600 seconds and saves it to Redis.
- **And** The system sends an email containing the OTP to the user's registered email address.
- **And** The system redirects the user to the Email Verification page with a success message.

#### Scenario 2: Registration failed due to email already in use (Alternative Path)
- **Given** The guest is on the Account Registration page.
- **When** The guest enters an email address that already exists and is active in the database.
- **And** The guest fills in all other fields and clicks the "Register" button.
- **Then** The system queries the database and detects that the email already exists.
- **And** The system blocks the registration process.
- **And** The system displays the error message: "Email already in use".
- **And** The system does not generate an OTP or write a new user record.

#### Scenario 3: Registration failed due to invalid input data (Edge Case)
- **Given** The guest is on the Account Registration page.
- **When** The guest clicks the "Register" button while leaving required fields empty, entering an invalid email format (e.g., `abc@`), or entering a weak password.
- **Then** The system performs client-side and server-side validation.
- **And** The system blocks the registration request from hitting the database.
- **And** The system displays corresponding error messages under each invalid field (e.g., "Invalid email address format", "Password must be at least 8 characters long").

---

### 2. Email Verification (F-AUTH-02)

#### Scenario 1: Successful account activation via OTP (Happy Path)
- **Given** The user has just registered and is on the Email Verification page.
- **When** The user enters the correct OTP received in their email.
- **And** The user clicks the "Verify" button.
- **Then** The system queries Redis to verify the validity and expiration status of the OTP.
- **And** The system confirms that the OTP is valid and unexpired (within 600 seconds).
- **And** The system updates the user's status in the database to `'active'`.
- **And** The system displays a success message and redirects the user to the Login page.

#### Scenario 2: Successful account activation via URL Token (Alternative Path)
- **Given** The user receives an activation email containing a link with a URL token.
- **When** The user clicks the activation link (sending a GET request to the system).
- **Then** The system extracts the token from the URL and validates it against Redis.
- **And** The system updates the user's status in the database to `'active'`.
- **And** The system displays an activation success screen and redirects the user to the Login page.

#### Scenario 3: Verification failed due to expired OTP/Token (Edge Case)
- **Given** The user enters the OTP or clicks the activation link more than 600 seconds after registration.
- **When** The user submits the verification request.
- **Then** The system checks Redis and finds that the OTP/Token has expired or does not exist.
- **And** The system keeps the user's status as `'inactive'` in the database.
- **And** The system displays an error message: "Verification code has expired or is invalid. Please request a new code."

---

### 3. User Authentication / Login (F-AUTH-03)

#### Scenario 1: Successful login via traditional credentials (Happy Path)
- **Given** The user has an active account (status `'active'`).
- **When** The user enters their correct Email and Password on the Login page and clicks "Login".
- **Then** The system compares the hash of the entered password with the hashed password stored in the database.
- **And** The system confirms the hashes match.
- **And** The system generates a JSON Web Token (JWT) containing `user_id`, `user_role`, and a 24-hour expiration.
- **And** The system returns the JWT to the client.
- **And** The system redirects the user to the dashboard.

#### Scenario 2: Successful login via Google OAuth2 - Existing User (Happy Path)
- **Given** The user has an active account linked to their Google account.
- **When** The user clicks "Login with Google" and completes authentication.
- **Then** The system receives and verifies the Google ID Token.
- **And** The system finds a matching Google ID in the database.
- **And** The system confirms the user status is active.
- **And** The system issues a new JWT (24-hour expiration) and logs the user into the dashboard.

#### Scenario 3: Google OAuth2 login - Automatic Registration (Alternative Path)
- **Given** The visitor does not have an account in the system database.
- **When** The visitor clicks "Login with Google" and completes authentication.
- **Then** The system verifies the Google ID Token and finds no matching Google ID in the database.
- **And** The system automatically registers a new user record with status `'active'`, plan `'Free'`, and syncs the full name and email from Google.
- **And** The system issues a new JWT (24-hour expiration) and logs the user into the dashboard.

#### Scenario 4: Login blocked for banned account (Edge Case)
- **Given** The user's account has a status of `'banned'` in the database.
- **When** The user tries to log in using traditional credentials or Google OAuth2.
- **Then** The system verifies the credentials but detects that the user status is `'banned'`.
- **And** The system blocks access.
- **And** The system returns the error message: "Your account has been locked due to violations of our Terms of Service".
- **And** The system does not issue a JWT.

---

### 4. User Session Termination / Logout (F-AUTH-04)

> [!IMPORTANT]
> To prevent JWT reuse after logout, the system must add the incoming JWT to a Redis blacklist database with a Time-To-Live (TTL) matching the token's remaining expiration time.

#### Scenario 1: Successful logout (Happy Path)
- **Given** The user is logged in with a valid JWT.
- **When** The user clicks the "Logout" button on the navigation bar.
- **Then** The system retrieves the token from the Request Header.
- **And** The system calculates the remaining time-to-live (TTL) of the token.
- **And** The system adds the JWT to the Redis blacklist with the calculated TTL.
- **And** The client-side clears the token from LocalStorage/Cookies.
- **And** The system redirects the user's browser view to the Landing Page.

#### Scenario 2: Rejected API requests using a logged-out JWT (Edge Case)
- **Given** The user has successfully logged out, and their JWT is blacklisted in Redis.
- **When** An API request is sent using the blacklisted JWT.
- **Then** The auth middleware checks Redis and identifies the JWT as blacklisted.
- **And** The system rejects the request immediately.
- **And** The system returns HTTP `401 Unauthorized` with a message stating the session has expired.

---

### 5. Forgot Password Recovery (F-AUTH-05)

#### Scenario 1: Successful password reset request (Happy Path)
- **Given** The user does not remember their password and is on the "Forgot Password" page.
- **When** The user enters their registered Email address and clicks "Submit".
- **Then** The system confirms the email exists in the database.
- **And** The system generates a temporary password reset token.
- **And** The system sends an email containing a unique reset URL with the token (e.g., `/reset-password?token=xxxx`).
- **And** The system displays the message: "A password reset link has been sent to your email".

#### Scenario 2: Successful password reset (Happy Path)
- **Given** The user clicks the password reset link from their email and is on the Password Reset page.
- **When** The user enters a new valid password and clicks "Update Password".
- **Then** The system validates that the token is valid and has not expired.
- **And** The system hashes the new password using bcrypt.
- **And** The system updates the user's password record in the database.
- **And** The system deletes the reset token to prevent reuse.
- **And** The system redirects the user to the login screen with a success message.

---

### 6. Profile Customization (F-AUTH-06)

#### Scenario 1: Successful profile and avatar update (Happy Path)
- **Given** The user is authenticated and is on the Profile Edit page.
- **When** The user enters a new display name and uploads an image file (`avatar.jpg`, size 1.2 MB).
- **And** The user clicks "Save Changes".
- **Then** The system validates that the uploaded file is a JPEG/PNG and its size is $\le$ 2MB.
- **And** The system uploads the avatar image to AWS S3.
- **And** The system updates the display name and S3 URL in the database.
- **And** The system returns the updated fields to the client and displays a success message.

#### Scenario 2: Profile update failed due to file size exceeding limit (Edge Case)
- **Given** The user is editing their profile.
- **When** The user attempts to upload an avatar image that is 2.5 MB (exceeding the 2MB limit).
- **And** The user clicks "Save Changes".
- **Then** The system blocks the upload immediately.
- **And** The system displays the error: "Uploaded file size exceeds the 2MB limit. Please choose another file".
- **And** The user's profile database records remain unchanged.

#### Scenario 3: Profile update failed due to unsupported file format (Edge Case)
- **Given** The user is editing their profile.
- **When** The user selects a `.gif` image or a `.pdf` file.
- **And** The user clicks "Save Changes".
- **Then** The system detects an invalid file format.
- **And** The system blocks the upload and returns the error: "Unsupported file format. Only JPEG and PNG are allowed".

---

## 📂 PART 2: DOCUMENT MANAGEMENT (F-DOC)

### 7. Document Upload (F-DOC-01)

> [!WARNING]
> Storage limits must be checked strictly. The system must verify that the user's current storage usage (`storage_used`) plus the size of the uploaded file does not exceed the limit specified by their subscription plan.

#### Scenario 1: Successful private document upload within storage quota (Happy Path)
- **Given** The user is active, on the Free plan (limit 200MB, currently using 50MB).
- **When** The user uploads `advanced_math.pdf` (10MB) and selects "Private" visibility.
- **And** The user clicks "Upload".
- **Then** The system verifies the user is active (not `'overlimitstorage'`).
- **And** The system calculates that the combined storage (60MB) is $\le$ 200MB.
- **And** The system uploads the file to AWS S3.
- **And** The system extracts the raw text contents of the document for full-text indexing.
- **And** The system saves the document record in the database with visibility `'private'`.
- **And** The system adds exactly 10,485,760 bytes (10MB) to the user's `storage_used` in the database.
- **And** The system displays the file in the user's personal document library.

#### Scenario 2: Successful public document upload routed to moderation queue (Happy Path)
- **Given** The user is active and has sufficient storage quota.
- **When** The user uploads `lecture_notes.docx` (5MB), selects "Public" visibility, and clicks "Upload".
- **Then** The system verifies storage quota and uploads the file to AWS S3.
- **And** The system extracts the raw text contents.
- **And** The system saves the document record with visibility `'public'` and status `'pending'`.
- **And** The system routes the file to the admin moderation queue.
- **And** The system increases the user's `storage_used` by 5MB.
- **And** The system displays: "Your document is pending admin approval before it can be public".

#### Scenario 3: Upload blocked due to 'overlimitstorage' account status (Edge Case)
- **Given** The user's account has a status of `'overlimitstorage'`.
- **When** The user attempts to upload any file.
- **Then** The system blocks the upload request immediately.
- **And** The system displays the warning: "Your storage has exceeded the plan limit. Please delete files or upgrade your plan to upload".

#### Scenario 4: Upload blocked because new file exceeds remaining storage quota (Edge Case)
- **Given** The user is on the Free plan (200MB limit) and has used 190MB.
- **When** The user attempts to upload a document of size 15MB.
- **Then** The system calculates that the combined storage would be 205MB (exceeding the 200MB limit).
- **And** The system rejects the upload.
- **And** The system returns the error: "Upload failed: file size exceeds remaining storage quota".

#### Scenario 5: Upload rejected due to unsupported file format (Edge Case)
- **Given** The user attempts to upload a file with extension `.key` (Keynote) or `.png`.
- **When** The user selects the file and clicks upload.
- **Then** The system checks the file extension.
- **And** The system blocks the upload because it is not one of `.pdf`, `.docx`, `.txt`, `.md`.
- **And** The system returns the error: "Unsupported file format".

---

### 8. Document Tagging (F-DOC-02)

#### Scenario 1: Tagging a document with both existing and new tags (Happy Path)
- **Given** The user is uploading or editing a document.
- **When** The user enters the tags `"LinearAlgebra"` (already exists in the database) and `"MidtermExam"` (a new tag, 11 characters).
- **And** The user saves the document.
- **Then** The system checks the database:
  - Reuses the existing tag ID for `"LinearAlgebra"`.
  - Creates a new tag definition record for `"MidtermExam"`.
- **And** The system writes association records to the `document_tag_mapping` table.
- **And** The system displays both tags on the document info card.

#### Scenario 2: Tag creation blocked because length exceeds 30 characters (Edge Case)
- **Given** The user is tagging a document.
- **When** The user inputs a tag that is 31 characters long: `"advanced-applied-mathematics-31"`.
- **And** The user tries to save the document.
- **Then** The system blocks the request.
- **And** The system displays the validation warning: "Tag length cannot exceed 30 characters".

---

### 9. Personal Storage Access (F-DOC-03)

#### Scenario 1: Successfully accessing active personal document list (Happy Path)
- **Given** The user is logged in with status `'active'`.
- **When** The user opens the "My Documents" page.
- **Then** The system queries the database for all active documents where `user_id` matches the user and `deleted_at` is NULL.
- **And** The system returns and displays all corresponding private, public, and pending documents.

#### Scenario 2: Access to personal document library blocked due to over-limit status (Edge Case)
- **Given** The user's account has a status of `'overlimitstorage'`.
- **When** The user attempts to access the "My Documents" page.
- **Then** The system intercepts and blocks the request.
- **And** The system displays a locked screen stating: "Your storage space is locked. Please delete files or upgrade your account to restore access".

---

### 10. Document Preview and Download (F-DOC-04)

> [!IMPORTANT]
> The in-browser rendering time for PDF, Word previews must not exceed 3.0 seconds to maintain a premium user experience.

#### Scenario 1: Guest or user viewing a public document preview (Happy Path)
- **Given** A document has visibility `'public'` and status `'active'`.
- **When** A guest user or any logged-in user clicks on the document to preview it.
- **Then** The system renders the document preview in the browser within 3.0 seconds without downloading.
- **And** The response data includes the document ID, title, file type, file size in bytes, S3 presigned URL, created timestamp (`created_at`), and description.

#### Scenario 2: Guest prompted to log in before downloading a public file (Alternative Path)
- **Given** A guest user is previewing a public document.
- **When** The guest clicks the "Download" button.
- **Then** The system blocks the download.
- **And** The system displays a Login Popup prompting the guest to sign in.
- **And** Once the user successfully signs in, the download starts automatically, and the response data includes the document ID, title, file type, file size in bytes, S3 presigned URL, created timestamp (`created_at`), and description.

#### Scenario 3: Non-owners blocked from accessing private, pending, or rejected files (Edge Case)
- **Given** Document A owned by User X has visibility `'private'`, `'pending'`, or `'rejected'`.
- **When** User Y (who is not the owner or an administrator) attempts to view or download Document A.
- **Then** The system denies access.
- **And** The system returns HTTP `403 Forbidden` or a "Document not found/unauthorized" message.

---

### 11. Search Execution (F-DOC-05)

#### Scenario 1: Fast public search execution (Happy Path)
- **Given** A user or guest is on the Search page.
- **When** The user inputs the keyword `"calculus"` and presses enter.
- **Then** The system queries document titles, tags, and extracted text content.
- **And** The system filters out any soft-deleted, private, pending, or rejected documents.
- **And** The system returns matching active public results in less than 1.5 seconds.

---

### 12. Share Link Generation (F-DOC-06)

#### Scenario 1: Generating a read-only share link for a private document (Happy Path)
- **Given** The user is the owner of the document `"Term Paper"`.
- **When** The user selects "Generate Share Link" from the settings menu.
- **Then** The system generates a unique cryptographic hash (or UUID).
- **And** The system saves the token to the document record in the database.
- **And** The system displays a public URL (e.g., `aistudyhub.com/shared/doc-xxxx`).
- **And** Anyone accessing this URL can preview the document in read-only mode, regardless of whether the document is private.

---

### 13. Document Metadata Modification (F-DOC-07)

#### Scenario 1: Changing document privacy from private to public triggers moderation (Happy Path)
- **Given** The user owns a document that is currently `'private'`.
- **When** The user edits the document, changes visibility to "Public", and clicks save.
- **Then** The system updates visibility to `'public'`.
- **And** The system resets the document's moderation status to `'pending'`.
- **And** The system routes the document to the admin moderation queue.
- **And** The system displays: "Your changes have been saved. The document has been submitted for admin approval".

---

### 14. Document Soft-Deletion (F-DOC-08)

#### Scenario 1: Soft-deleting a file and updating user storage (Happy Path)
- **Given** The user owns `slides.pdf` (20MB) and their current storage usage is 120MB.
- **When** The user clicks the "Delete" button.
- **Then** The system displays a Confirmation Modal.
- **And** When the user confirms the action.
- **And** The system writes the current timestamp to the document's `deleted_at` field.
- **And** The system sets the status to `'deleted'`.
- **And** The system subtracts 20MB from the user's `storage_used` (120MB - 20MB = 100MB) and updates the database record.

---

## 🤝 PART 3: SOCIAL LEARNING & INTERACTION (F-SOC)

### 15. Review and Rating (F-SOC-01)

#### Scenario 1: Rating and commenting on a public document (Happy Path)
- **Given** An authenticated user is viewing an approved public document.
- **When** The user selects a `5` star rating and enters the comment `"Great notes, thanks!"`.
- **Then** The system saves the review in the database.
- **And** The system recalculates the average rating of the document.
- **And** The system updates the average rating in the document table.
- **And** The system displays the review and the updated rating score on the page.

#### Scenario 2: Blocked rating submission due to score out of bounds (Edge Case)
- **Given** A user attempts to bypass the client UI and submits a rating score of `0` or `6`.
- **When** The server receives the request.
- **Then** Server validation detects the rating score is out of the 1 to 5 range.
- **And** The system rejects the request and returns an invalid request error.

---

### 16. Abuse & Content Reporting (F-SOC-02)

#### Scenario 1: Submitting an abuse report (Happy Path)
- **Given** An authenticated user is viewing a public document.
- **When** The user clicks "Report", selects "Copyright Infringement", adds details `"Copied textbook content"`, and clicks submit.
- **Then** The system saves the report record with a default status of `'pending'`.
- **And** The system sends an alert to the Admin Dashboard.
- **And** The system displays: "Thank you. Your report has been submitted for administrator review".

---

## 🤖 PART 4: AI CHATBOT (F-AI-RAG)

### 17. Multi-Document Contextual Chat (F-AI-01)

> [!NOTE]
> To control API costs, the system uses the AI Guard middleware to intercept chat requests and block users who have exceeded their plan's daily chat limits.

#### Scenario 1: Multi-document chat within quota (Happy Path)
- **Given** The user is Premium, and has used 10 out of their 500 daily requests.
- **When** The user selects `macroeconomics.pdf` and `exam_notes.docx` (total context is under 100 pages).
- **And** The user enters the query `"Compare demand-pull and cost-push inflation?"` and submits (no session ID provided).
- **Then** The AI Guard middleware verifies that the usage is within quota.
- **And** The system initializes a new Chat Session.
- **And** The system generates embeddings for the query.
- **And** The system executes a similarity search against the Vector DB restricted to the selected files.
- **And** The system sends the query and matching context to the LLM API.
- **And** The system returns the answer, page citations, and file references within 5.0 seconds.
- **And** The system saves the query, response, and citations as JSON in the messages table.
- **And** The system increments the user's daily request count by 1.

#### Scenario 2: Request blocked due to daily quota exceeded (Edge Case)
- **Given** A Free plan user has already used 15 requests today.
- **When** The user submits a new chat query.
- **Then** The AI Guard middleware detects that the daily quota has been reached.
- **And** The system blocks the request immediately without calling the LLM API.
- **And** The system returns the error: "Daily AI request limit reached. Please upgrade to Premium for more request chat".
- **And** The request count does not increase.

---

### 18. Single Document Contextual Chat (F-AI-02)

#### Scenario 1: Requesting a summary of an open document (Happy Path)
- **Given** The user is viewing a document.
- **When** The user clicks "Summarize Document".
- **Then** The system verifies the user's daily quota.
- **And** The system restricts the vector search context to the current document ID.
- **And** The system sends the request to the LLM API.
- **And** The system returns the generated summary on the chat interface.
- **And** The system increments the user's daily request count by 1.

---

### 19. Chat Session Management (F-AI-03)

#### Scenario 1: Viewing and renaming active chat sessions (Happy Path)
- **Given** The user has active chat histories in the database.
- **When** The user opens the Chat History sidebar.
- **Then** The system displays all chat sessions belonging to the user where `deleted_at` is NULL.
- **And** When the user renames a session to `"Macroeconomics Review"`, the system updates the title in the database and reflects the changes in the UI.

#### Scenario 2: Deleting a chat session (Happy Path)
- **Given** The user is looking at their chat history.
- **When** The user clicks the "Delete" icon on a chat session.
- **Then** The system sets the current timestamp in the session's `deleted_at` field in the database.
- **And** The system removes the session from the visible chat history list.

---

## 🛠️ PART 5: ADMIN DASHBOARD (F-ADM)

### 20. Content Moderation (F-ADM-01)

#### Scenario 1: Admin approving a pending document (Happy Path)
- **Given** The administrator is on the Admin Moderation Queue, and document `math_101.pdf` is `'pending'` with visibility `'public'`.
- **When** The admin clicks the "Approve" button.
- **Then** The system updates the document status in the database to `'active'`.
- **And** The document is now visible in public search results.
- **And** The system generates a notification for the owner: "Your document 'math_101.pdf' has been approved and is now public".

#### Scenario 2: Admin rejecting a pending document (Happy Path)
- **Given** The administrator is on the Admin Moderation Queue.
- **When** The admin clicks "Reject", inputs the reason `"File contains advertisements"`, and submits.
- **Then** The system updates the document's moderation status to `'rejected'`.
- **And** The system saves the rejection reason to the document record.
- **And** The system creates a notification for the owner: "Your document has been rejected. Reason: File contains advertisements".
- **And** The document remains hidden from the public library.

---

### 21. Violation Review (F-ADM-02)

#### Scenario 1: Resolving a report and deleting the document (Happy Path)
- **Given** The admin is reviewing a pending report for `cheat_sheet.pdf` uploaded by User A.
- **When** The admin clicks "Confirm Report".
- **Then** The system updates the report status to `'resolved'`.
- **And** The system changes the document status to `'deleted'` (removing it from all views).
- **And** The system logs a violation entry against User A's profile.
- **And** The system sends an automated warning notification to User A.

#### Scenario 2: Dismissing a report (Alternative Path)
- **Given** The admin is reviewing an abuse report.
- **When** The admin clicks "Dismiss Report".
- **Then** The system updates the report status to `'rejected'`.
- **And** The document remains `'active'` and `'public'`.

---

### 22. Account Warnings & Sanctions (F-ADM-03)

> [!CAUTION]
> When an administrator bans an account, the system must immediately add all active session JWTs belonging to that user to the Redis Blacklist to terminate their session.

#### Scenario 1: Banning a user account (Happy Path)
- **Given** The admin is on the User Management page.
- **When** The admin selects User B and clicks the "Ban Account" button.
- **Then** The system updates User B's status to `'banned'` in the database.
- **And** The system retrieves all active JWT identifiers for User B.
- **And** The system writes these JWTs to the Redis blacklist database.
- **And** All subsequent API requests using User B's active session tokens are rejected immediately.

---

### 23. Aggregation and Stats (F-ADM-04)

#### Scenario 1: Loading metrics on the Admin Dashboard (Happy Path)
- **Given** The administrator opens the Admin Dashboard.
- **When** The page finishes loading.
- **Then** The system executes SQL aggregation commands to retrieve:
  - Total signups grouped by time.
  - Total count of successful document uploads.
  - Combined storage size of files stored on AWS S3.
  - Sum of successful invoice revenues for the current month.
- **And** The system renders these metrics on charts and tables in less than 2.0 seconds.

---

## 💳 PART 6: SUBSCRIPTION & PAYMENT (F-MON)

### 24. Subscription Purchase Flow (F-MON-01)

#### Scenario 1: Initiating upgrade and generating QR code (Happy Path)
- **Given** The user is on the Free plan and is on the Pricing Page.
- **When** The user selects the Premium plan and clicks "Upgrade Now".
- **Then** The system creates an invoice in the database with status `'pending'`, the target subscription plan, and the price.
- **And** The system calls the payment gateway API (MoMo/VietQR/VNPay) to retrieve a dynamic QR code.
- **And** The system displays the payment QR code and payment instructions containing the unique invoice UUID.

---

### 25. Webhook Automation Flow (F-MON-02)

> [!IMPORTANT]
> Upgrading plans, extending expiration dates, and unlocking storage limits must be executed within a single Atomic Database Transaction block to prevent data inconsistencies in case of payment processing failures.

#### Scenario 1: Handling successful payment webhook for a normal user (Happy Path)
- **Given** An invoice with status `'pending'` exists in the database.
- **When** The payment gateway sends a callback POST request containing successful payment info.
- **Then** The system verifies the payload signature using the configured Client Secret.
- **And** The system runs an atomic transaction to:
  - Update the invoice status to `'success'`.
  - Set the user's plan to Premium.
  - Extend the plan expiration date (`plan_expires_at`) to exactly 30 days from the current timestamp.
- **And** The system returns HTTP `200 OK` to the gateway.

#### Scenario 2: Successful webhook unlocks storage-locked user (Happy Path / Unlock)
- **Given** A user with status `'overlimitstorage'` has a pending invoice.
- **When** The system receives a valid callback webhook confirming payment.
- **Then** The system verifies the signature.
- **And** The system executes the atomic database transaction:
  - Updates the invoice status to `'success'`.
  - Sets the plan to Premium (expanding limit to 10GB).
  - Resets the user status to `'active'`, unlocking the storage.
  - Sets `plan_expires_at` to current time + 30 days.
- **And** The system returns HTTP `200 OK` to the gateway.

#### Scenario 3: Rejecting invalid webhook calls (Edge Case / Security Violation)
- **Given** External request attempts to trigger the webhook endpoint.
- **When** The payload signature does not match the computed hash using the Client Secret.
- **Then** The system detects the signature mismatch.
- **And** The system blocks the request immediately.
- **And** The system returns HTTP `401 Unauthorized` or `403 Forbidden`.
- **And** No changes are made to the database.

---

### 26. Daily AI Limit Reset (F-MON-03)

#### Scenario 1: First chat request of the day initializes Redis key (Happy Path)
- **Given** The user has not sent any chat queries today.
- **When** The user submits their first query.
- **Then** The system checks Redis for the key `user:ai_limit:{user_id}:{today_date}` and finds it does not exist.
- **And** The system uses the atomic `INCR` command to create the key and sets its value to `1`.
- **And** The system sets a 24-hour expiration time (TTL) on the Redis key.
- **And** The system allows the query to proceed to the LLM API.

#### Scenario 2: Request within limit increments counter (Happy Path)
- **Given** The user has already sent 5 requests, so the Redis key value is `5`.
- **When** The user submits a new query.
- **Then** The system increments the Redis counter to `6`.
- **And** The system verifies `6` is less than or equal to their plan limit (e.g., 15 for Free).
- **And** The system allows the query to proceed to the LLM API.

#### Scenario 3: Request blocked when limit is exceeded (Edge Case)
- **Given** The user's Redis counter has reached the plan limit of `15`.
- **When** The user submits a query.
- **Then** The system reads the counter value (15) and blocks the request.
- **And** The system returns a quota exceeded error without calling the LLM API.

---

### 27. Check Subscription Expiration - Lazy Downgrade (F-MON-04)

> [!NOTE]
> The system utilizes a **Lazy Downgrade** mechanism. Subscription checks are not performed by periodic background cron jobs; instead, the check is triggered lazily when the user makes any API request after their expiration date.

#### Scenario 1: Request from active Premium user (Happy Path)
- **Given** The user is Premium and `plan_expires_at` is in the future.
- **When** The user makes an API request.
- **Then** The system verifies the current time is less than `plan_expires_at`.
- **And** The system allows the request to proceed without changing plan details.

#### Scenario 2: Lazy downgrade - Current storage under Free limit (Happy Path / Downgrade)
- **Given** The user is Premium, `plan_expires_at` has passed, and their current storage usage is 120MB.
- **When** The user makes an API request.
- **Then** The system detects that the current time exceeds `plan_expires_at`.
- **And** The system downgrades the user's plan to `'Free'` in the database.
- **And** The system sets `plan_expires_at` to NULL.
- **And** The system compares the storage usage (120MB) against the Free plan limit (200MB).
- **And** The system confirms it is within limits and keeps user status as `'active'`.
- **And** The system executes the original API request.

#### Scenario 3: Lazy downgrade - Current storage over Free limit triggers storage lock (Edge Case)
- **Given** The user is Premium, `plan_expires_at` has passed, and their current storage usage is 1.5 GB.
- **When** The user makes an API request.
- **Then** The system detects expiration.
- **And** The system downgrades the user's plan to `'Free'` and sets `plan_expires_at` to NULL.
- **And** The system compares the storage usage (1.5 GB) against the Free plan limit (200MB).
- **And** The system detects that storage exceeds the limit.
- **And** The system updates the user's status to `'overlimitstorage'` in the database.
- **And** The system blocks the API request.
- **And** The system returns a warning page or an error status showing that storage is locked.

---

## 🏁 PART 7: DEFINITION OF DONE (DoD)

A feature is considered "Done" and ready for production only when it meets the following criteria:

1. **Unit & Integration Tests:**
   - Minimum code coverage of 80% for core modules (Authentication, RAG Pipeline, Payment Webhook).
   - 100% of automated Happy Path test cases pass successfully before merging code.
2. **Performance Constraints:**
   - Multi-document chat/summary API under 100 pages must respond in $\le$ 5.0 seconds.
   - Standard full-text search query execution must return results in $\le$ 1.5 seconds.
   - Document preview in-browser rendering must complete in $\le$ 3.0 seconds.
3. **Security & Authorization:**
   - Strict authorization check: Users must not be able to view, edit, or delete other users' documents unless public or accessed via a valid share link.
   - Passwords must be hashed with bcrypt.
   - Logged out or banned user JWTs must be added to the Redis Blacklist in real-time.
4. **User Experience & Responsiveness:**
   - Interface is fully responsive on both desktop and mobile viewports.
   - The `'overlimitstorage'` status must clearly prompt the user on how to resolve the storage lock (e.g., delete files or upgrade).
