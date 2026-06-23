# Refined Functional Requirements: AI Study Hub

This document contains the refined, unambiguous, and measurable Software Requirements Specification (SRS) for the **AI Study Hub**, extracted from the [Business Process.md](file:///Users/chithien/code/SWP_Project/Business%20Process.md) and aligned with the constraints in the [Vision & Scope Document](file:///Users/chithien/code/SWP_Project/vision-scope-ai-study-hub.md).

---

## Part 1: Authentication & Profile (F-AUTH)

### 1. Account Registration (F-AUTH-01)
- **F-AUTH-01.1:** The system shall present a registration form accepting Email Address, Password, and Full Name.
- **F-AUTH-01.2:** The system shall query the database to verify if the provided Email Address exists.
- **F-AUTH-01.3:** The system shall block the registration process and return an "Email already in use" error if the Email Address is found in the database.
- **F-AUTH-01.4:** The system shall hash the password using a secure hashing algorithm (e.g., bcrypt) and save the new user account record to the database with a status field value of `'inactive'` and default the package assignment to the `Free` plan.
- **F-AUTH-01.5:** The system shall generate a secure one-time password (OTP) or activation token, persist it to a caching layer (e.g., Redis) with an expiration duration of 600 seconds, and transmit it to the user's registered Email Address.

### 2. Email Verification (F-AUTH-02)
- **F-AUTH-02.1:** The system shall accept an OTP input or a URL token parameter via a GET request.
- **F-AUTH-02.2:** The system shall verify the validity and expiration status of the token or OTP from the caching layer.
- **F-AUTH-02.3:** The system shall update the user account status field to `'active'` in the database if the token or OTP is valid and unexpired, enabling login access.

### 3. User Authentication / Login (F-AUTH-03)
- **F-AUTH-03.1:** The system shall authenticate users via Email/Password credentials or Google OAuth2 protocol.
- **F-AUTH-03.2:** The system shall compare the user-entered password hash with the stored hash in the database during traditional login.
- **F-AUTH-03.3:** The system shall verify the Google OAuth2 ID Token, extract the Google ID, and verify its existence in the database.
- **F-AUTH-03.4:** The system shall automatically register a new user account with status `'active'` and the default `Free` plan if the Google ID does not exist in the database.
- **F-AUTH-03.5:** The system shall query the user's account status and block authentication, returning an account locked message, if the status is `'banned'`.
- **F-AUTH-03.6:** The system shall generate a JSON Web Token (JWT) containing user ID, user role, and session expiration (e.g., 24 hours), returning it to the client upon successful validation.

### 4. User Session Termination / Logout (F-AUTH-04)
- **F-AUTH-04.1:** The system shall invalidate the active session when a logout request is received.
- **F-AUTH-04.2:** The system shall write the incoming JWT to a Redis blacklist database with a Time-To-Live (TTL) matching the token's remaining expiration time to prevent unauthorized reuse.
- **F-AUTH-04.3:** The system shall redirect the user's browser view to the landing page.

### 5. Forgot Password Recovery (F-AUTH-05)
- **F-AUTH-05.1:** The system shall accept an Email Address on the password recovery interface.
- **F-AUTH-05.2:** The system shall verify the email's existence in the database, generate a temporary password reset token, and email a unique reset URL containing the token if verified.
- **F-AUTH-05.3:** The system shall accept a new password and validation token from the reset password interface.
- **F-AUTH-05.4:** The system shall validate, hash, and update the password field in the database, clear the reset token, and redirect the user to the login screen.

### 6. Profile Customization (F-AUTH-06)
- **F-AUTH-06.1:** The system shall accept display name updates and profile image file uploads on the user profile interface.
- **F-AUTH-06.2:** The system shall validate that the uploaded profile image is in a supported format (JPEG, PNG) and does not exceed 2MB in file size.
- **F-AUTH-06.3:** The system shall upload validated profile images to AWS S3, update the user profile table record with the new display name and S3 URL, and return the updated fields.

---

## Part 2: Document Management (F-DOC)

### 7. Document Upload (F-DOC-01)
- **F-DOC-01.1:** The system shall accept file uploads in `.pdf`, `.docx`, `.txt`, and `.md` formats.
- **F-DOC-01.2:** The system shall reject upload requests from users with status `'overlimitstorage'` and return a storage-limit warning.
- **F-DOC-01.3:** The system shall verify that the combined total of the user's current storage usage (`storage_used`) and the size of the uploaded file is less than or equal to the storage limit (`storage_limit`) defined by their active subscription plan.
- **F-DOC-01.4:** The system shall transmit the uploaded file to AWS S3 and extract the textual payload to support full-text indexing.
- **F-DOC-01.5:** The system shall write a document record to the database with visibility `'private'` if private is selected, status `'pending'` (awaiting admin approval) if public is selected.
- **F-DOC-01.6:** The system shall increment the user's database field `storage_used` by the exact file size in bytes.

### 8. Document Tagging (F-DOC-02)
- **F-DOC-02.1:** The system shall allow users to attach existing tags or create new tags (up to 30 characters each) during document upload or profile edit flows.
- **F-DOC-02.2:** The system shall query if the tag text exists in the database and create a new record in the tag definition table if it does not.
- **F-DOC-02.3:** The system shall write association records to the document-tag mapping database table.

### 9. Personal Storage Access (F-DOC-03)
- **F-DOC-03.1:** The system shall block access to the personal document library and return a storage lock warning page if the user's status is `'overlimitstorage'`.
- **F-DOC-03.2:** The system shall query and return active documents matching the user's ID where the deletion timestamp is null.

### 10. Document Preview and Download (F-DOC-04)
- **F-DOC-04.1:** The system shall allow any user, including guests, to view document previews that have a database visibility of `'public'`.
- **F-DOC-04.2:** The system shall display a login popup prompting guest users to authenticate before initiating a file download request.
- **F-DOC-04.3:** The system shall restrict preview and download actions on documents with a visibility of `'private'`, status `'pending'`, or `'rejected'` to the document owner and admin users.
- **F-DOC-04.4:** The system shall render PDF, Word previews directly in the browser window within 3.0 seconds.

### 11. Search Execution (F-DOC-05)
- **F-DOC-05.1:** The system shall perform a database or search index query scanning document titles, tags, and extracted text content for user-supplied keywords.
- **F-DOC-05.2:** The system shall return matching search results in less than 1.5 seconds.
- **F-DOC-05.3:** The system shall filter out documents marked as deleted, private, or pending from public search results.

### 12. Share Link Generation (F-DOC-06)
- **F-DOC-06.1:** The system shall generate a unique cryptographic hash or UUID associated with the target document upon user request.
- **F-DOC-06.2:** The system shall write the token to the document record's sharing link field in the database.
- **F-DOC-06.3:** The system shall present a public URL containing the sharing token that provides read-only preview privileges.

### 13. Document Metadata Modification (F-DOC-07)
- **F-DOC-07.1:** The system shall permit users to edit titles, tags, and privacy settings of documents they own.
- **F-DOC-07.2:** The system shall change the document status to `'pending'` and place it in the admin moderation queue if the user changes the document's privacy state from Private to Public.

### 14. Document Soft-Deletion (F-DOC-08)
- **F-DOC-08.1:** The system shall display a confirmation modal prior to deleting a document.
- **F-DOC-08.2:** The system shall write the current timestamp to the deletion field and change the document's status to `'deleted'`.
- **F-DOC-08.3:** The system shall calculate the owner's new storage usage by subtracting the deleted file size in bytes and update the user record in the database.

---

## Part 3: Social Learning & Interaction (F-SOC)

### 15. Review and Rating (F-SOC-01)
- **F-SOC-01.1:** The system shall allow authenticated users to submit a numerical rating (integer values 1 to 5) and a comment on public documents.
- **F-SOC-01.2:** The system shall write the review record to the database and recalculate the document's average rating.

### 16. Abuse & Content Reporting (F-SOC-02)
- **F-SOC-02.1:** The system shall allow authenticated users to submit a violation report describing copyright issues or terms of service violations.
- **F-SOC-02.2:** The system shall insert a report record with a default status of `'pending'` and send an alert notification to the admin dashboard.

---

## Part 4: AI Chatbot (F-AI-RAG)

### 17. Multi-Document Contextual Chat (F-AI-01)
- **F-AI-01.1:** The system shall accept user chat queries and an array of target document IDs.
- **F-AI-01.2:** The system shall intercept queries using an AI Guard middleware to verify daily usage limits: if the current date matches the user's last request date, and the daily request counter is equal to or greater than the quota limit of their subscription plan, the system shall block the query and return an upgrade warning.
- **F-AI-01.3:** The system shall initialize a new chat session containing the selected documents list if no session identifier is provided.
- **F-AI-01.4:** The system shall generate embedding vectors for the user query, execute a similarity search against the vector database for the selected documents, and extract the matching context blocks.
- **F-AI-01.5:** The system shall send the retrieved context blocks and prompt to the LLM API (Gemini/OpenAI) and return the response, page citations, and file references in less than 5.0 seconds for context payloads under 100 pages.
- **F-AI-01.6:** The system shall record the query, response, and citation references as structured JSON in the messages database table.
- **F-AI-01.7:** The system shall increment the user's daily request count and set the last request date to the current date.

### 18. Single Document Contextual Chat (F-AI-02)
- **F-AI-02.1:** The system shall execute single-document queries and summarizations following the same rate-limiting checks, restricting the semantic search context window to the specific document ID.
- **F-AI-02.2:** The system shall return the response and update the request count in the database.

### 19. Chat Session Management (F-AI-03)
- **F-AI-03.1:** The system shall return active chat sessions for the authenticated user where the deletion timestamp is null.
- **F-AI-03.2:** The system shall fetch and display the chronological chat message history for the selected session.
- **F-AI-03.3:** The system shall allow users to modify chat session titles or mark the deletion timestamp to hide the session.

---

## Part 5: Admin Dashboard (F-ADM)

### 20. Content Moderation (F-ADM-01)
- **F-ADM-01.1:** The system shall present pending public document uploads on the admin interface.
- **F-ADM-01.2:** The system shall change the document visibility to `'public'` when approved by an administrator.
- **F-ADM-01.3:** The system shall change the document status to `'rejected'` and capture the rejection reason when rejected by an administrator.
- **F-ADM-01.4:** The system shall write a notifications record in the database for the document owner indicating the moderation outcome.

### 21. Violation Review (F-ADM-02)
- **F-ADM-02.1:** The system shall present pending reports on the admin moderation interface.
- **F-ADM-02.2:** The system shall update the report status to `'resolved'`, change the associated document status to `'rejected'` or `'deleted'`, and log a violation entry against the uploader in the database upon report confirmation.
- **F-ADM-02.3:** The system shall update the report status to `'rejected'` and maintain the document's visibility `'public'` status upon report dismissal.

### 22. Account Warnings & Sanctions (F-ADM-03)
- **F-ADM-03.1:** The system shall allow administrators to issue warning alerts or apply account bans based on user violations.
- **F-ADM-03.2:** The system shall set the user account status to `'banned'` and add the user's active JWTs to the Redis blacklist, invalidating the session immediately.

### 23. Aggregation and Stats (F-ADM-04)
- **F-ADM-04.1:** The system shall aggregate and display system metrics, including user signups, successful uploads, total storage usage, and monthly invoice revenues, using SQL aggregation commands.

---

## Part 6: Subscription & Payment (F-MON)

### 24. Subscription Purchase Flow (F-MON-01)
- **F-MON-01.1:** The system shall create an invoice record with status `'pending'` containing the target subscription plan ID when an upgrade is initiated.
- **F-MON-01.2:** The system shall query the payment gateway API (MoMo, VNPay, or VietQR) to retrieve a dynamic QR code containing the invoice amount and UUID.

### 25. Webhook Automation Flow (F-MON-02)
- **F-MON-02.1:** The system shall expose a secure webhook endpoint to receive transaction notification callbacks.
- **F-MON-02.2:** The system shall verify the webhook's payload signature using the configured client secret to prevent tampering.
- **F-MON-02.3:** The system shall update the invoice status to `'success'`, change the user's plan to Premium, extend the expiration date to 30 days from the current timestamp, and set the user's status back to `'active'` (if it was `'overlimitstorage'`) within an atomic database transaction block upon webhook verification.

### 26. Daily AI limit reset (Lazy Update + Redis Counter) (F-MON-03)
- **F-MON-03.1:** The system shall intercept AI chat requests and check for daily quota limits in Redis using a key matching the pattern `user:ai_limit:{user_id}:{yyyy-mm-dd}`.
- **F-MON-03.2:** The system shall increment the Redis counter using atomic instructions (e.g., `INCR`).
- **F-MON-03.3:** The system shall set a 24-hour expiration time (TTL) on the Redis key when the counter is initialized for the first time in a day.
- **F-MON-03.4:** The system shall block the request and return a quota exceeded error without calling the LLM API if the counter value exceeds the subscription limit.

### 27. Check subscription expiry (Lazy Downgrade) (F-MON-04)
- **F-MON-04.1:** The system shall run a subscription check when a user makes an API request.
- **F-MON-04.2:** The system shall update the user's package to the Free tier, set the plan expiration to null, and compare the user's current storage usage against the Free tier limit (200MB) if the current time exceeds `plan_expires_at` and the plan is not Free.
- **F-MON-04.3:** The system shall set the user status to `'overlimitstorage'` and restrict file upload, document viewing, and AI chat features if the storage usage exceeds the Free tier limit.
