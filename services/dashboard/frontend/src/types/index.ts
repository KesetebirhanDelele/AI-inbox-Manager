/**
 * TypeScript type definitions for the Email Management Dashboard.
 */

export interface User {
  username: string;
  role: string;
  session_created: string;
  session_expires: string;
  last_activity: string;
}

export interface Email {
  id: number;
  email_id: string;
  subject: string;
  from_address: string;
  received_date: string;
  body_preview: string;
  current_folder: string;
  is_read: boolean;
  latest_category?: string;
  latest_confidence?: number;
  latest_company?: string;
}

export interface Classification {
  id: number;
  category: string;
  confidence: number;
  company_name?: string;
  position?: string;
  timestamp: string;
  classifier_version: string;
}

export interface Approval {
  id: number;
  email_id: number;
  classification_id: number;
  status: 'pending' | 'approved' | 'rejected' | 'overridden';
  email_subject: string;
  email_from: string;
  email_received_date: string;
  category: string;
  confidence: number;
  company_name?: string;
  position?: string;
}

export interface ProcessRun {
  id: number;
  run_timestamp: string;
  total_emails: number;
  interview_requests: number;
  organized: number;
  spam_deleted: number;
  categories_breakdown: Record<string, number>;
  duration_seconds?: number;
  status: string;
}

export interface WhitelistCompany {
  id: number;
  company_name: string;
  added_date: string;
  added_by: string;
  notes?: string;
}

export interface SummaryStats {
  today_total_emails: number;
  today_interview_requests: number;
  total_interview_requests: number;
  today_organized: number;
  today_spam_deleted: number;
  week_total_emails: number;
  week_interview_requests: number;
  last_run_timestamp?: string;
  pending_approvals: number;
  inbox_count: number;
  yesterday_total_emails?: number;
}

export interface ScheduleConfig {
  interval_minutes: number;
  batch_size: number;
  last_updated?: string;
  updated_by?: string;
}

export interface InboxCount {
  count: number;
  synced: boolean;
}

export interface CategoryBreakdown {
  category: string;
  count: number;
}

export interface AccuracyMetrics {
  total_approvals: number;
  approved: number;
  overridden: number;
  rejected: number;
  override_rate: number;
  avg_confidence: number;
  low_confidence_count: number;
}

export interface EmailDetail {
  email: {
    id: number;
    email_id: string;
    subject: string;
    from_address: string;
    received_date: string;
    full_body: string;
    current_folder: string;
    is_read: boolean;
    fetch_timestamp: string;
    last_updated: string;
  };
  classifications: Classification[];
  actions: EmailAction[];
}

export interface EmailAction {
  id: number;
  action_type: string;
  from_folder?: string;
  to_folder?: string;
  performed_by: string;
  performed_at: string;
  reason?: string;
}

// Interview request types

export interface InterviewRequest {
  id: number;
  email_id: string;
  subject: string;
  from_address: string;
  received_date: string;
  company_name?: string;
  position?: string;
  confidence: number;
  classification_timestamp: string;
  body_preview: string;
  current_folder: string;
  is_read: boolean;
  student_name?: string;
  interview_type?: string;
  interview_date?: string;
  interview_time?: string;
  contact_name?: string;
  interview_event_id?: number;
}

export interface UpcomingInterview {
  interview_event_id: number;
  student_name?: string;
  company_name?: string;
  position?: string;
  interview_type?: string;
  interview_date?: string;
  interview_time?: string;
  interview_timezone?: string;
  interview_format?: string;
  meeting_link?: string;
  contact_name?: string;
  contact_email?: string;
}

// Checklist types

export interface ChecklistSubStep {
  key: string;
  label: string;
  is_completed: boolean;
  completed_by?: string;
  completed_at?: string;
}

export interface ChecklistMainStep {
  key: string;
  label: string;
  is_completed: boolean;
  completed_by?: string;
  completed_at?: string;
  sub_steps: ChecklistSubStep[];
}

export interface ChecklistResponse {
  interview_event_id: number;
  sub_type: string;
  sub_type_label: string;
  steps: ChecklistMainStep[];
  total_steps: number;
  completed_steps: number;
  progress_percent: number;
}

// Interview notification types

export interface NotificationSummary {
  id: number;
  interview_event_id: number;
  template_id?: string;
  email_subject?: string;
  recipient_email?: string;
  email_status: string;
  auto_send_eligible: boolean;
  missing_fields?: string[];
  created_at?: string;
  sub_type?: string;
  company_name?: string;
  position_title?: string;
  confidence?: number;
  student_name?: string;
  student_username?: string;
}

export interface NotificationDetail {
  id: number;
  interview_event_id: number;
  template_id?: string;
  email_subject?: string;
  email_body?: string;
  recipient_email?: string;
  email_status: string;
  auto_send_eligible: boolean;
  missing_fields?: string[];
  reviewed_by?: string;
  reviewed_at?: string;
  sent_at?: string;
  send_error?: string;
  created_at?: string;
  sub_type?: string;
  company_name?: string;
  position_title?: string;
  contact_name?: string;
  contact_email?: string;
  interview_date?: string;
  interview_time?: string;
  interview_timezone?: string;
  interview_format?: string;
  confidence?: number;
  is_job_machine?: boolean;
  student_name?: string;
  student_username?: string;
  student_personal_email?: string;
  student_assigned_gmail?: string;
  student_phone?: string;
  email_db_id?: number;
  email_subject_original?: string;
}

export interface ReviewQueueItem {
  event_id: number;
  draft_id: number | null;
  state: 'ready' | 'blocked' | 'needs_student' | 'no_draft' | 'approved' | 'failed' | string;
  blockers: string[];
  warnings: string[];
  can_approve: boolean;
  will_happen: string;
  student: {
    id: number;
    name?: string;
    username?: string;
    personal_email?: string;
    assigned_gmail?: string;
    phone?: string;
  } | null;
  interview: {
    type?: string;
    company?: string;
    position?: string;
    date?: string;
    time?: string;
    timezone?: string;
    format?: string;
    contact_name?: string;
    contact_email?: string;
    confidence?: number;
  };
  email: {
    id: number;
    subject?: string;
    from_address?: string;
    received_date?: string;
    excerpt: string;
  } | null;
  authenticity: {
    verdict: 'looks_genuine' | 'needs_check' | 'likely_job_board';
    against: string[];
    for: string[];
    note: string;
  };
  draft: { subject?: string; body?: string; recipient_email?: string; status: string } | null;
  preview: { call: string; text: string; email_subject?: string } | null;
  sequence: { status: string; started_at?: string; ack_channel?: string } | null;
}

export interface ReviewQueue {
  escalation_enabled: boolean;
  count: number;
  items: ReviewQueueItem[];
}

export interface InterviewEventRecord {
  event_id: number;
  student_name?: string;
  student_email?: string;
  company_name?: string;
  position_title?: string;
  sub_type: string;
  interview_type?: string;
  interview_date?: string;
  interview_time?: string;
  interview_timezone?: string;
  interview_format?: string;
  notification_status?: string;
  notified_at?: string;
  recipient_email?: string;
  created_at: string;
  draft_id?: number | null;
  subject?: string;
  from_address?: string;
  received_date?: string;
  confidence?: number;
}

export interface StudentInfo {
  id: number;
  username: string;
  full_name?: string;
  personal_email?: string;
  assigned_gmail?: string;
  phone_number?: string;
  is_active: boolean;
  last_synced_at?: string;
  created_at?: string;
}
