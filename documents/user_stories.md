# User Stories: AI Study Hub

This document maps the refined functional requirements of the AI Study Hub project into agile, value-driven User Stories. Each story adheres to the format: **"As a [Role], I want to [Action], So that [Value]"**.

---

## 1. Authentication & Profile Management (F-AUTH)

- **US-AUTH-01 (Account Registration):** 
  As a Guest, I want to register a new account using my Email Address, Full Name, and Password, So that I can access the system's personalized storage and study tools.
- **US-AUTH-02 (Email Verification):** 
  As a Guest, I want to verify my email using a one-time password (OTP) sent to my inbox, So that I can activate my account and log in securely.
- **US-AUTH-03 (Account Authentication):** 
  As a Guest, I want to log in using either my credentials or my Google account, So that I can securely access my personal dashboard and materials.
- **US-AUTH-04 (Session Termination):** 
  As a User, I want to log out of my active session, So that I can prevent others from accessing my account on a shared device.
- **US-AUTH-05 (Password Recovery):** 
  As a User, I want to request a password reset email and set a new password, So that I can recover access to my account if I forget my credentials.
- **US-AUTH-06 (Profile Customization):** 
  As a User, I want to update my display name and upload a profile picture, So that I can personalize my user profile on the platform.

---

## 2. Document Management & Storage (F-DOC)

- **US-DOC-01 (Document Upload):** 
  As a User, I want to upload files in PDF, Word, PowerPoint, Text, or Markdown format, So that I can store them in my personal cloud workspace.
- **US-DOC-02 (Document Tagging):** 
  As a User, I want to attach tags to my documents, So that I can easily group and categorize my study materials by subject, chapter, or topic.
- **US-DOC-03 (Personal Document Library):** 
  As a User, I want to view all my uploaded documents and see their approval status, So that I can manage my storage limits and file privacy.
- **US-DOC-04 (In-Browser Preview):** 
  As a User, I want to preview PDF, Word, and PowerPoint files directly in the browser, So that I can read my files immediately without waiting to download them.
- **US-DOC-05 (Advanced Search):** 
  As a User or Guest, I want to search for documents by searching for text inside them, their titles, or their tags, So that I can quickly find the exact resources I need.
- **US-DOC-06 (File Sharing Link):** 
  As a User, I want to generate a unique read-only sharing URL for my documents, So that I can share them with other students without changing the file's ownership.
- **US-DOC-07 (Metadata Update):** 
  As a User, I want to update my document's title, tags, and privacy settings, So that I can maintain accurate information and control who has access to my documents.
- **US-DOC-08 (Document Soft-Deletion):** 
  As a User, I want to soft-delete my files, So that I can free up my storage space while having a safety period to recover them before permanent deletion.

---

## 3. Social Learning & Interaction (F-SOC)

- **US-SOC-01 (Review and Rating):** 
  As a User, I want to rate public documents with stars and write comments, So that I can share my feedback on their quality and help other students find useful materials.
- **US-SOC-02 (Content Reporting):** 
  As a User, I want to report public documents that violate copyright policies or contain inappropriate content, So that I can help maintain a safe and legal shared library.

---

## 4. RAG AI Chatbot (F-AI-RAG)

- **US-AI-01 (Multi-Document Chat):** 
  As a User, I want to select multiple documents and ask questions to the AI chatbot, So that I can get context-specific answers with page number citations across my files.
- **US-AI-02 (Single Document Summary):** 
  As a User, I want to request summaries and ask questions about a single open document, So that I can understand long papers or notes in a fraction of the time.
- **US-AI-03 (Chat History Management):** 
  As a User, I want to view my past chat sessions, rename them, or delete them, So that I can refer back to previous study sessions and keep my chat history organized.

---

## 5. Admin Dashboard (F-ADM)

- **US-ADM-01 (Content Moderation):** 
  As an Admin, I want to review pending public document requests and approve or reject them, So that I can prevent low-quality or copyrighted material from appearing in the public library.
- **US-ADM-02 (Abuse Report Management):** 
  As an Admin, I want to resolve reports against public files and mark violations in the system, So that I can enforce the platform's terms of service and remove illegal uploads.
- **US-ADM-03 (Account Penalization):** 
  As an Admin, I want to issue warnings or ban user accounts that violate platform policies, So that I can maintain a safe environment for all learners.
- **US-ADM-04 (System Overview Reports):** 
  As an Admin, I want to view charts showing user growth, storage usage, and subscription revenue, So that I can monitor the system's performance and monthly business growth.

---

## 6. Subscription & Payments (F-MON)

- **US-MON-01 (Tier Upgrade):** 
  As a User, I want to select a Premium plan and generate a dynamic QR code for payment, So that I can upgrade my account to access more storage and more daily AI chatbot requests.
- **US-MON-02 (AI Usage Warning):** 
  As a User, I want to check my daily AI request count and get warned if I reach my quota limit, So that I can budget my usage or decide to upgrade my subscription.
- **US-MON-03 (Subscription Expiry Warning):** 
  As a User, I want to be notified and guided if my account is downgraded and exceeds the Free storage limit, So that I know how to clear space or renew my subscription to regain full access.
