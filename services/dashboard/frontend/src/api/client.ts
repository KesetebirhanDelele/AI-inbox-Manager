/**
 * API client for communicating with the Email Management Dashboard backend.
 */

import axios, { AxiosInstance } from 'axios';
import type {
  User,
  Email,
  Approval,
  ProcessRun,
  WhitelistCompany,
  SummaryStats,
  CategoryBreakdown,
  AccuracyMetrics,
  EmailDetail,
  NotificationSummary,
  NotificationDetail,
  StudentInfo,
  InterviewRequest,
  UpcomingInterview,
  ChecklistResponse,
  ScheduleConfig,
  InboxCount,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      withCredentials: true, // Include cookies for session authentication
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  // Authentication
  async login(username: string, password: string): Promise<{ message: string; username: string }> {
    const response = await this.client.post('/api/auth/login', { username, password });
    return response.data;
  }

  async logout(): Promise<{ message: string }> {
    const response = await this.client.post('/api/auth/logout');
    return response.data;
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get('/api/auth/me');
    return response.data;
  }

  // Approvals
  async getPendingApprovals(): Promise<Approval[]> {
    const response = await this.client.get('/api/approvals/pending');
    return response.data;
  }

  async approveEmail(approvalId: number, action: string, targetFolder?: string, notes?: string): Promise<any> {
    const response = await this.client.post(`/api/approvals/${approvalId}/approve`, {
      action,
      target_folder: targetFolder,
      notes,
    });
    return response.data;
  }

  async overrideClassification(
    approvalId: number,
    newCategory: string,
    action: string,
    targetFolder?: string,
    notes?: string,
    addToWhitelist = false
  ): Promise<any> {
    const response = await this.client.post(`/api/approvals/${approvalId}/override`, {
      new_category: newCategory,
      action,
      target_folder: targetFolder,
      notes,
      add_to_whitelist: addToWhitelist,
    });
    return response.data;
  }

  async rejectApproval(approvalId: number, notes?: string): Promise<any> {
    const response = await this.client.post(`/api/approvals/${approvalId}/reject`, null, {
      params: { notes },
    });
    return response.data;
  }

  // Inbox
  async getCurrentInbox(refresh = false): Promise<Email[]> {
    const response = await this.client.get('/api/inbox/current', {
      params: { refresh },
    });
    return response.data;
  }

  async getUnreadEmails(refresh = false): Promise<Email[]> {
    const response = await this.client.get('/api/inbox/unread', {
      params: { refresh },
    });
    return response.data;
  }

  async getInboxCount(refresh = false): Promise<InboxCount> {
    const response = await this.client.get('/api/inbox/count', {
      params: { refresh },
    });
    return response.data;
  }

  async getInboxHistory(limit = 50, offset = 0, folder?: string): Promise<Email[]> {
    const response = await this.client.get('/api/inbox/history', {
      params: { limit, offset, folder },
    });
    return response.data;
  }

  async getEmailDetail(emailId: number): Promise<EmailDetail> {
    const response = await this.client.get(`/api/inbox/${emailId}`);
    return response.data;
  }

  // Email Actions
  async classifyEmail(emailId: number): Promise<any> {
    const response = await this.client.post(`/api/emails/${emailId}/classify`);
    return response.data;
  }

  async moveEmail(emailId: number, targetFolder: string): Promise<any> {
    const response = await this.client.post(`/api/emails/${emailId}/move`, {
      target_folder: targetFolder,
    });
    return response.data;
  }

  async deleteEmail(emailId: number, reason?: string): Promise<any> {
    const response = await this.client.post(`/api/emails/${emailId}/delete`, null, {
      params: { reason },
    });
    return response.data;
  }

  async markEmailRead(emailId: number, markAsRead: boolean): Promise<any> {
    const response = await this.client.post(`/api/emails/${emailId}/mark-read`, {
      mark_as_read: markAsRead,
    });
    return response.data;
  }

  // Statistics
  async getSummaryStats(): Promise<SummaryStats> {
    const response = await this.client.get('/api/stats/summary');
    return response.data;
  }

  async getCategoryBreakdown(startDate?: string, endDate?: string): Promise<CategoryBreakdown[]> {
    const response = await this.client.get('/api/stats/categories', {
      params: { start_date: startDate, end_date: endDate },
    });
    return response.data;
  }

  async getAccuracyMetrics(): Promise<AccuracyMetrics> {
    const response = await this.client.get('/api/stats/accuracy');
    return response.data;
  }

  async getEngineeringKPIs(): Promise<{
    ai_cost_today_usd: number;
    avg_duration_seconds_7d: number | null;
    failure_rate_7d: number;
    run_count_7d: number;
    failed_run_count_7d: number;
    db_storage_used_bytes: number | null;
    db_storage_cap_bytes: number | null;
    db_storage_pct: number | null;
  }> {
    const response = await this.client.get('/api/stats/engineering-kpis');
    return response.data;
  }

  async getProcessingRuns(limit = 10): Promise<ProcessRun[]> {
    const response = await this.client.get('/api/stats/processing-runs', {
      params: { limit },
    });
    return response.data;
  }

  async getTrends(days = 7): Promise<any> {
    const response = await this.client.get('/api/stats/trends', {
      params: { days },
    });
    return response.data;
  }

  async runProcessing(): Promise<any> {
    const response = await this.client.post('/api/stats/run-processing');
    return response.data;
  }

  // Interview Requests
  async getInterviewRequests(limit = 50, offset = 0): Promise<InterviewRequest[]> {
    const response = await this.client.get('/api/interviews', {
      params: { limit, offset },
    });
    return response.data;
  }

  async getInterviewCount(): Promise<{ count: number }> {
    const response = await this.client.get('/api/interviews/count');
    return response.data;
  }

  async getUpcomingInterviews(): Promise<UpcomingInterview[]> {
    const response = await this.client.get('/api/interviews/upcoming');
    return response.data;
  }

  async getInterviewDetail(emailId: number): Promise<any> {
    const response = await this.client.get(`/api/interviews/${emailId}`);
    return response.data;
  }

  async getInterviewEvents(): Promise<import('../types').InterviewEventRecord[]> {
    const response = await this.client.get('/api/interviews/events');
    return response.data;
  }

  // Whitelist
  async getWhitelist(): Promise<WhitelistCompany[]> {
    const response = await this.client.get('/api/whitelist');
    return response.data;
  }

  async addToWhitelist(companyName: string, notes?: string): Promise<WhitelistCompany> {
    const response = await this.client.post('/api/whitelist', {
      company_name: companyName,
      notes,
    });
    return response.data;
  }

  async removeFromWhitelist(companyId: number): Promise<any> {
    const response = await this.client.delete(`/api/whitelist/${companyId}`);
    return response.data;
  }

  // Notifications
  async getPendingNotifications(limit = 50, offset = 0): Promise<NotificationSummary[]> {
    const response = await this.client.get('/api/notifications/pending', {
      params: { limit, offset },
    });
    return response.data;
  }

  async getSentNotifications(limit = 50, offset = 0): Promise<NotificationSummary[]> {
    const response = await this.client.get('/api/notifications/sent', {
      params: { limit, offset },
    });
    return response.data;
  }

  async getNotificationDetail(notificationId: number): Promise<NotificationDetail> {
    const response = await this.client.get(`/api/notifications/${notificationId}`);
    return response.data;
  }

  async getNotificationByEmail(emailId: number): Promise<NotificationDetail | null> {
    const response = await this.client.get(`/api/notifications/by-email/${emailId}`);
    return response.data;
  }

  async approveNotification(notificationId: number): Promise<any> {
    const response = await this.client.post(`/api/notifications/${notificationId}/approve`);
    return response.data;
  }

  async editNotification(
    notificationId: number,
    subject?: string,
    body?: string,
    recipientEmail?: string,
    sendAfterEdit = false
  ): Promise<any> {
    const response = await this.client.post(`/api/notifications/${notificationId}/edit`, {
      email_subject: subject,
      email_body: body,
      recipient_email: recipientEmail,
      send_after_edit: sendAfterEdit,
    });
    return response.data;
  }

  async rejectNotification(notificationId: number, reason?: string): Promise<any> {
    const response = await this.client.post(`/api/notifications/${notificationId}/reject`, {
      reason,
    });
    return response.data;
  }

  // Students
  async getStudents(activeOnly = true): Promise<StudentInfo[]> {
    const response = await this.client.get('/api/notifications/students/list', {
      params: { active_only: activeOnly },
    });
    return response.data;
  }

  async getStudent(studentId: number): Promise<StudentInfo> {
    const response = await this.client.get(`/api/notifications/students/${studentId}`);
    return response.data;
  }

  // Checklist
  async getChecklist(interviewEventId: number): Promise<ChecklistResponse> {
    const response = await this.client.get(`/api/checklist/${interviewEventId}`);
    return response.data;
  }

  async toggleChecklistStep(
    interviewEventId: number,
    stepKey: string,
    isCompleted: boolean
  ): Promise<{ interview_event_id: number; step_key: string; is_completed: boolean }> {
    const response = await this.client.put(`/api/checklist/${interviewEventId}/toggle`, {
      step_key: stepKey,
      is_completed: isCompleted,
    });
    return response.data;
  }

  // Schedule info (read-only: the real cron interval and per-run email cap)
  async getScheduleConfig(): Promise<ScheduleConfig> {
    const response = await this.client.get('/api/schedule/config');
    return response.data;
  }

  // Reports
  async getStudentActivity(): Promise<any[]> {
    const response = await this.client.get('/api/stats/student-activity');
    return response.data;
  }

  async getCompanyTracker(): Promise<any[]> {
    const response = await this.client.get('/api/stats/company-tracker');
    return response.data;
  }

  async getMissedInterviews(): Promise<any[]> {
    const response = await this.client.get('/api/stats/missed-interviews');
    return response.data;
  }

  async getWeeklySummary(): Promise<any> {
    const response = await this.client.get('/api/stats/weekly-summary');
    return response.data;
  }

  async getOffers(limit = 20): Promise<any[]> {
    const response = await this.client.get('/api/stats/offers', { params: { limit } });
    return response.data;
  }

  async getTodayEmails(): Promise<any[]> {
    const response = await this.client.get('/api/stats/today-emails');
    return response.data;
  }

  async getHourlyVolume(): Promise<{ hour: number; count: number }[]> {
    const response = await this.client.get('/api/stats/hourly-volume');
    return response.data;
  }

  async getRejectionTrend(): Promise<{ date: string; count: number }[]> {
    const response = await this.client.get('/api/stats/rejection-trend');
    return response.data;
  }

  async getInterviewPipeline(): Promise<any> {
    const response = await this.client.get('/api/stats/pipeline');
    return response.data;
  }

  // Health Check
  async healthCheck(): Promise<{ status: string; environment: string; database: string }> {
    const response = await this.client.get('/health');
    return response.data;
  }
}

export const apiClient = new ApiClient();
