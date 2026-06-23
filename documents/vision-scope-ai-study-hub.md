# VISION AND SCOPE DOCUMENT

## PROJECT: AI-POWERED STUDY DOCUMENT MANAGEMENT SYSTEM (AI STUDY HUB)

---

## 1. BUSINESS REQUIREMENTS

### 1.1. Business Background
In modern university environments, the volume of study and research documents for students is growing rapidly. These materials include lecture slides, e-textbooks, reference materials, past exams, group assignments, and personal study notes.

However, students face inefficient information management because their files are scattered across too many platforms such as Google Drive, Zalo, Messenger, Facebook Groups, personal emails, and local physical drives (USB, hard drives). This fragmentation leads to lost files, wasted time searching for materials, and a lack of knowledge transfer between student cohorts, which directly harms study efficiency and exam preparation.

### 1.2. Business Opportunity & Problem Statements
AI Study Hub was created to solve the core pain points of students and learners through a comprehensive technology solution:

| Current Problem | Practical Impact | Solution by AI Study Hub |
| :--- | :--- | :--- |
| **Scattered Data** | Users waste 15-30 minutes searching for old files; links and files are easily lost when Google Drive links are deleted or Zalo/Messenger chats are cleared. | A centralized cloud repository that allows scientific organization by subjects and flexible tagging. |
| **Inefficient Search** | Users can only search by file names, making it impossible to find text hidden inside documents. | An Advanced **Full-text Search** feature that scans all text inside PDF, Word, and PowerPoint files. |
| **Information Overload** | Students waste hours reading long PDFs to find a single formula, concept, or key point. | An AI Chatbot powered by **RAG (Retrieval-Augmented Generation)** architecture to summarize and answer questions directly based on documents. |
| **Manual & Fragmented Sharing**| Sharing is temporary via chat applications, lacking structured knowledge transfer between student generations. | A **Public Library** organized by universities/majors, moderated by Admins, and supported by a community rating system. |
| **Hardware & Cost Limits** | Personal device storage is limited; upgrading personal cloud drives (Google One, iCloud) is expensive for students. | Optimized cloud storage (AWS S3) with flexible monetization plans (Free & Premium) designed for students. |

#### Comparison with existing market solutions:
*   **Google Drive / OneDrive / Dropbox:** Only offer static file storage and search based on file names or basic metadata. They do not have built-in AI assistants that can read, understand, and chat directly with documents.
*   **Zalo / Messenger / Facebook Groups:** Files expire and are deleted automatically after a short period (especially Zalo). They lack clear folder structures and do not support deep full-text search.
*   **Traditional document-sharing websites (tailieu.vn, 123doc, etc.):** Complicated paid download models, low-quality/spam documents, and complete lack of interactive AI tools for personalized learning.

### 1.3. Business Objectives
To establish the practical value of the project, the business objectives are defined quantitatively as follows:
*   **Data Centralization:** Migrate and consolidate at least 80% of target students at partnered universities from scattered storage platforms to AI Study Hub within the first 6 months of operation.
*   **Efficiency Boost:** Reduce document search times by 70% and reduce reading/summarizing times for long academic papers by 50% for active users.
*   **Community Knowledge Sharing:** Build a shared public library with at least 5,000 high-quality, moderated academic documents in the first year.
*   **Sustainable Monetization:** Achieve a minimum conversion rate of 5% from free users to Premium subscribers within 6 months of launching payment features, ensuring positive cash flow for system operations.

### 1.4. Success Metrics
Project success will be measured by two sets of core metrics:

#### 1.4.1. System Metrics
*   **AI Latency:** Response time for the RAG-based AI Chatbot on documents under 100 pages must be under 5 seconds.
*   **AI Accuracy:** Citation accuracy must exceed 90% to prevent AI hallucination outside the scope of the selected documents.
*   **Search Speed:** Full-text search queries must return matches in under 1.5 seconds.
*   **Preview Speed:** Online document preview rendering (PDF, Word) must load in under 3 seconds.

#### 1.4.2. Business Metrics
*   **User Engagement:** Reach a minimum of 1,000 Monthly Active Users (MAU) within 3 months of deployment.
*   **Payment Automation:** 100% automated subscription upgrades via dynamic QR codes (VietQR/MoMo webhooks) without any manual intervention.
*   **Retention Rate:** Premium subscription renewal rate must exceed 60% per 30-day billing cycle.

### 1.5. Vision Statement
The long-term vision of the AI Study Hub project focuses on three core actors, delivering unique value to each of them:

*   **For the Guests (Unauthenticated Visitors):** AI Study Hub serves as an open, welcoming portal that showcases the power of AI-assisted learning. Through a beautiful landing page and interactive mockups, guests can quickly explore key features, understand the benefits of dynamic document chat, and easily register for a free account via a seamless 1-click Google OAuth2 sign-in. The platform aims to convert curious visitors into active learners instantly.
*   **For the Users (Students & Learners):** AI Study Hub is an intelligent, personalized study companion. Unlike static cloud storage tools, it empowers users to centralize all their learning materials, search deep inside their files with full-text search, and directly converse with single documents or entire folders. The RAG-powered chatbot reads their notes and textbooks to provide instant summaries, answers, and precise citations, turning passive files into active knowledge to save hours of exam preparation.
*   **For the Admins (System Administrators):** AI Study Hub provides a comprehensive, secure, and automated management center. It equips administrators with tools to moderate public document uploads, review copyright violation flags from the community, monitor system health logs, and track subscription revenues in real-time. By automating payments and package upgrades, the system minimizes operational overhead, allowing admins to focus on quality control and community safety.

### 1.6. Business Risks
1.  **Copyright & Legal Risks:** Users might upload copyrighted books or confidential school exam papers to the Public Library.
    *   *Mitigation:* Implement a strict moderation workflow. All documents marked as "Public" must be approved by an Admin (manually or via automated keyword filters) before becoming visible. Add a simple community reporting tool (Report) for quick copyright takedown requests.
2.  **AI API Consumption Costs:** Using commercial LLM APIs (like Gemini or OpenAI) can lead to extremely high costs if user requests spike without control.
    *   *Mitigation:* Implement strict Backend Rate Limiting Middleware. Set daily query quotas for each account package, cache answers for identical queries in the same context, and optimize prompt token sizes.
3.  **User Adoption Resistance:** Students are used to old tools (Google Drive, Zalo) and might be lazy to migrate.
    *   *Mitigation:* Design a modern, clean, and simple user experience (UX) with 1-click Google Login. Highlight the unique RAG AI chatbot features that general cloud storage platforms do not support.
4.  **Payment Processing Failures:** Network issues could prevent transaction webhooks from reaching our server, causing subscription delays for Premium users.
    *   *Mitigation:* Implement an automated periodic transaction reconciliation job and provide a clear transaction history dashboard so users can easily submit support tickets if an issue occurs.

### 1.7. Business Assumptions & Dependencies
*   **Assumptions:**
    *   Target users (students) own at least one personal device (computer or smartphone) with stable internet access and use modern web browsers (Chrome, Safari, Edge).
    *   Students are willing to share high-quality study documents with the community in exchange for reputation points or short-term premium perks.
*   **Dependencies:**
    *   **LLM API Providers (Gemini/OpenAI):** System availability, speed, and pricing models depend directly on the AI API provider.
    *   **Third-Party Payment Gateways:** Automated subscription upgrades depend on stable APIs and webhooks from payment gateway partners (MoMo, VietQR/PayOS).

---

## 2. SCOPE & LIMITATIONS

### 2.1. Major Features
To track and manage requirements, each major feature is labeled with a unique ID:

*   **FEAT-AUTH: Authentication & Account Management**
    *   Email registration with activation link/OTP verification.
    *   Secure login using JSON Web Tokens (JWT).
    *   Fast login integration via Google OAuth2.
    *   Profile management (basic info, password changes).
*   **FEAT-DOC: Document Management & Categorization**
    *   Support uploads for `.pdf`, `.docx`, `.txt`, and `.md` files.
    *   Smart tagging system allowing users to categorize documents by subjects, chapters, or topics.
    *   Flexible privacy controls (Private for personal use / Public to share with the community after Admin approval).
*   **FEAT-FTS: Advanced Full-text Search**
    *   Super-fast queries by file titles and tags.
    *   Deep search inside document text, displaying matching snippets on the results page.
*   **FEAT-STG: Cloud Storage & Previews**
    *   Integration with AWS S3 for secure, distributed static file storage, completely isolated from the application server.
    *   Interactive built-in preview tool to read PDF, Word, and PowerPoint files online without downloading.
*   **FEAT-AI-RAG: Contextual AI Assistant (Retrieval-Augmented Generation)**
    *   Quick summarization of any selected document.
    *   Contextual chat based on a single file or a group of files (in a folder/subject) selected as the Context Window.
    *   Precise citations showing file names and page numbers for easy verification of AI responses.
    *   Chat session management (create, view, rename, and delete sessions).
*   **FEAT-MON: Subscriptions & Automated Payments**
    *   Subscription Dashboard displaying real-time storage usage (used/limit) and daily AI request quotas.
    *   Automated billing upgrades using dynamic QR codes (VietQR or MoMo sandbox) driven by background webhooks.
    *   Backend rate-limiting middleware (AI Guard) to block queries when free users exceed their daily quota.
*   **FEAT-SOC: Community Sharing & Social Learning**
    *   Public document library for student-to-student sharing.
    *   Community interactions: 1-5 star ratings and comment threads under public files.
    *   Reporting tool (Report) for inappropriate content or copyright violations.

### 2.2. Scope of Initial Release (MVP)
The MVP release will focus on core individual study management features, AI RAG capabilities, and automated payments:

*   **Authentication:** Traditional email/password signup + Google OAuth2.
*   **Document Management:** Upload PDF, Word, and PowerPoint files under 20MB. Manual tagging on upload. Private/Public privacy settings.
*   **Storage & Display:** AWS S3 integration and smooth online PDF document preview.
*   **Search:** Basic search by name/tags and basic Full-text Search within PDF content.
*   **AI Chatbot (RAG):**
    *   Chat based on a single file or folder context.
    *   Quick document summaries.
    *   Precise source citations (file name, page number).
    *   Chat history preservation.
*   **Monetization:**
    *   Dashboard for storage and daily AI usage tracking.
    *   Plans: **Free Plan** (200MB storage, max 15 AI chats/day) and **Premium Plan** (10GB storage, max 500 AI chats/day).
    *   Dynamic VietQR/MoMo sandbox payments with automated webhook activation.
    *   AI Guard middleware to block free users when limits are exceeded.
    *   Automatic subscription downgrade after 30 days. Access locks (upload/preview) if a downgraded account exceeds the Free 200MB limit (requires deletion of excess files or renewal).

### 2.3. Scope of Subsequent Releases
Future phases will introduce community-focused features and advanced AI capabilities:

*   **Social Hub:** Enable ratings and comments for public documents. Implement trending algorithms on the public Home page.
*   **Smart AI Enhancements:**
    *   **Auto-tagging:** AI automatically analyzes document text to suggest appropriate tags on upload.
    *   **Multimodal RAG:** Support AI extraction and analysis of charts and images inside PDFs.
    *   1-click automatic Mindmap and Flashcard generation from study documents.
*   **Advanced Monetization:**
    *   Group/Class Study Plans for shared storage and collaboration.
    *   **Gamified Points System:** Reward students with points when their public documents get high downloads/ratings. Points can be redeemed for extra AI requests or short-term Premium access.

### 2.4. Limitations & Exclusions
*   **No Online Editing:** AI Study Hub is a repository and reading companion. It does **not** include online document editors like Google Docs or Word Online. Users must download files to edit them locally.
*   **Non-text Formats Excluded:** The AI RAG system does not support audio, video, or compressed archives (`.zip`, `.rar`).
*   **RAG Context Window Limit:** To optimize API costs and latency, the total text sent as context per session is limited to the equivalent of 150 standard pages (approx. 60,000 words). If selected files exceed this limit, the system will ask the user to deselect files or upgrade plans.

---

## 3. BUSINESS CONTEXT

### 3.1. Stakeholder Profiles
Detailed breakdown of roles, attitudes, and expectations of the primary stakeholders:

| Stakeholder Group | Value Received | Attitude / Interest | Key Features of Interest | Constraints & Concerns |
| :--- | :--- | :--- | :--- | :--- |
| **Guest (Visitor)** | Get an overview of the platform and explore AI capabilities. | Curious, wants a quick trial without complicated setups. | Modern landing page, 1-click registration/login with Google. | Dislikes long signup processes or slow visual loading. |
| **User (Student/Learner)** | Save exam prep time, organize documents, summarize long texts, study efficiently. | Extremely high interest, expects high utility at an affordable price. | AI RAG Chatbot, Full-text Search, Document Preview, custom tags. | Concerned about cost of Premium, daily AI limits on Free plan, and data privacy of Private files. |
| **Admin (System Admin)** | Easily manage users, moderate public library, track automated billing. | Demands high security, clear dashboard controls, and quick moderation tools. | Content moderation panel, user management, revenue stats, system logs. | Concerned about copyright violations on Public uploads and manual workload before automation is stable. |
| **ChatbotService (AI)** | Provide precise semantic search results and accurate answers. | Requires stable hosting, high-bandwidth connection, and optimized vector DB. | Semantic search, LLM API connection, citation extraction. | Dependent on third-party LLM (Gemini/OpenAI) uptime and avoiding model hallucinations. |
| **Development & Ops Team** | Build a successful, modern product with commercial viability. | Eager, expects clean maintainable code and cost-optimized infrastructure. | Rate limiting middleware, webhook pipelines, vector DB indexing. | Limited initial budget for API consumption and tight MVP schedules. |

### 3.2. Project Priorities
Project dimensions mapped using the Karl Wiegers Priority Matrix:

| Project Dimension | Driver | Constraint | Degree of Freedom | Detailed Description |
| :--- | :--- | :--- | :--- | :--- |
| **Features** | | **X** (For MVP) | **X** (For Future) | For the MVP, the core features (Document Management, AI RAG, and Automated Payments) are strict constraints and must be fully functional. Community features are degrees of freedom for future releases. |
| **Quality** | **X** | | | Quality is a major driver to build user trust. AI accuracy (no hallucinations), reliable citations, S3 preview speed, and strict private file security are critical. |
| **Schedule** | | **X** | | The system must launch its MVP within 8-12 weeks to capture students' final exam seasons. |
| **Cost** | | | **X** | A 15% budget overflow on API costs is accepted during the initial launch phase to gather real user interaction data. |
| **Staff** | | **X** | | The team size is fixed (e.g., 2-3 Fullstack developers) and cannot be expanded during the MVP phase. |

### 3.3. Deployment Considerations
*   **Geographic Access:** Mostly accessed by university students within Vietnam. Traffic peaks are expected in evenings (19:00 - 24:00) and before final exams. Servers must use CDN configurations to optimize local response speeds.
*   **Infrastructure:** Requires AWS S3 for physical document storage and a fast Vector Database (e.g., pgvector on PostgreSQL, Qdrant, or Pinecone) for semantic vector search embeddings.
*   **Data Security:** Implement full SSL (HTTPS) encryption. Private documents must be fully secured using S3 Signed URLs to prevent unauthorized access.
*   **Data Migration:** Provide simple Drag & Drop upload tools so students can easily migrate collections from Google Drive.
*   **User Training:** Include a brief interactive tutorial on first-time login to teach users how to choose study contexts and write high-quality prompts for the AI RAG chatbot.
