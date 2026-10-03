import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { format } from 'date-fns';
import type { Email, NotificationDetail } from '../types';

// Sub-type display configuration
const SUB_TYPE_STYLES: Record<string, { label: string; bg: string; text: string }> = {
  interview_request: { label: 'Interview Request', bg: 'bg-purple-100', text: 'text-purple-800' },
  phone_screen: { label: 'Phone Screen', bg: 'bg-blue-100', text: 'text-blue-800' },
  client_screen: { label: 'Client Screen', bg: 'bg-indigo-100', text: 'text-indigo-800' },
  technical_interview: { label: 'Technical Round', bg: 'bg-teal-100', text: 'text-teal-800' },
  cancelled: { label: 'Cancelled', bg: 'bg-red-100', text: 'text-red-800' },
  rescheduled: { label: 'Rescheduled', bg: 'bg-yellow-100', text: 'text-yellow-800' },
};

const EMAIL_STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  draft: { bg: 'bg-gray-100', text: 'text-gray-800' },
  approved: { bg: 'bg-blue-100', text: 'text-blue-800' },
  sent: { bg: 'bg-green-100', text: 'text-green-800' },
  failed: { bg: 'bg-red-100', text: 'text-red-800' },
  rejected: { bg: 'bg-red-100', text: 'text-red-800' },
};

/**
 * Fetches and displays the full email body for an expanded email.
 */
const EmailBodyPanel = ({ emailId }: { emailId: number }) => {
  const [showFullBody, setShowFullBody] = useState(false);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['emailDetail', emailId],
    queryFn: () => apiClient.getEmailDetail(emailId),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="py-3 text-sm text-gray-500 italic">Could not load full email body.</div>
    );
  }

  const body = detail.email.full_body;
  if (!body) {
    return (
      <div className="py-3 text-sm text-gray-400 italic">No email body available.</div>
    );
  }

  const PREVIEW_LENGTH = 600;
  const isLong = body.length > PREVIEW_LENGTH;
  const displayBody = isLong && !showFullBody ? body.slice(0, PREVIEW_LENGTH) + '…' : body;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h5 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Email Body</h5>
        {detail.classifications && detail.classifications.length > 0 && (
          <div className="flex items-center gap-1">
            {detail.classifications.slice(0, 3).map((c, i) => (
              <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                {c.category} · {(c.confidence * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="bg-white border border-gray-200 rounded-md p-3">
        <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans break-words">
          {displayBody}
        </pre>
        {isLong && (
          <button
            onClick={() => setShowFullBody((v) => !v)}
            className="mt-2 text-xs text-primary-600 hover:underline"
          >
            {showFullBody ? 'Show less' : 'Show full email'}
          </button>
        )}
      </div>
    </div>
  );
};

/**
 * Inline panel shown below an expanded interview email.
 * Displays interview details, notification draft, and WhatsApp message.
 */
const InterviewDetailPanel = ({ emailId }: { emailId: number }) => {
  const queryClient = useQueryClient();
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editRecipient, setEditRecipient] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  const { data: notification, isLoading, error } = useQuery({
    queryKey: ['notificationByEmail', emailId],
    queryFn: () => apiClient.getNotificationByEmail(emailId),
    retry: false,
  });

  const editMutation = useMutation({
    mutationFn: (params: { id: number; subject: string; body: string; recipient: string; sendAfterEdit: boolean }) =>
      apiClient.editNotification(params.id, params.subject, params.body, params.recipient, params.sendAfterEdit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notificationByEmail', emailId] });
      queryClient.invalidateQueries({ queryKey: ['pendingNotifications'] });
      setIsEditing(false);
    },
  });

  const startEditing = (n: NotificationDetail) => {
    setEditSubject(n.email_subject || '');
    setEditBody(n.email_body || '');
    setEditRecipient(n.recipient_email || '');
    setIsEditing(true);
  };

  const handleSaveAndSend = (sendAfterEdit: boolean) => {
    if (!notification) return;
    editMutation.mutate({
      id: notification.id,
      subject: editSubject,
      body: editBody,
      recipient: editRecipient,
      sendAfterEdit,
    });
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (error || !notification) {
    return (
      <div className="py-4 text-center text-sm text-gray-500">
        No interview notification found for this email.
      </div>
    );
  }

  const subTypeStyle = SUB_TYPE_STYLES[notification.sub_type || ''] || {
    label: notification.sub_type || 'Unknown',
    bg: 'bg-gray-100',
    text: 'text-gray-800',
  };

  const emailStatusStyle = EMAIL_STATUS_STYLES[notification.email_status] || EMAIL_STATUS_STYLES.draft;
  const isPending = notification.email_status === 'draft';
  const isSent = notification.email_status === 'sent';

  return (
    <div className="space-y-4">
      {/* Interview Details */}
      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-2">Interview Details</h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <span className="text-xs text-gray-500 block">Type</span>
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${subTypeStyle.bg} ${subTypeStyle.text}`}>
              {subTypeStyle.label}
            </span>
          </div>
          {notification.company_name && (
            <div>
              <span className="text-xs text-gray-500 block">Company</span>
              <span className="text-sm text-gray-900">{notification.company_name}</span>
            </div>
          )}
          {notification.position_title && (
            <div>
              <span className="text-xs text-gray-500 block">Position</span>
              <span className="text-sm text-gray-900">{notification.position_title}</span>
            </div>
          )}
          {notification.interview_date && (
            <div>
              <span className="text-xs text-gray-500 block">Date / Time</span>
              <span className="text-sm text-gray-900">
                {notification.interview_date}
                {notification.interview_time && ` at ${notification.interview_time}`}
                {notification.interview_timezone && ` ${notification.interview_timezone}`}
              </span>
            </div>
          )}
          {notification.interview_format && (
            <div>
              <span className="text-xs text-gray-500 block">Format</span>
              <span className="text-sm text-gray-900 capitalize">{notification.interview_format}</span>
            </div>
          )}
          {notification.contact_name && (
            <div>
              <span className="text-xs text-gray-500 block">Contact</span>
              <span className="text-sm text-gray-900">
                {notification.contact_name}
                {notification.contact_email && ` (${notification.contact_email})`}
              </span>
            </div>
          )}
          {notification.confidence !== undefined && (
            <div>
              <span className="text-xs text-gray-500 block">Confidence</span>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  notification.confidence >= 0.95
                    ? 'bg-green-100 text-green-800'
                    : notification.confidence >= 0.80
                    ? 'bg-yellow-100 text-yellow-800'
                    : 'bg-orange-100 text-orange-800'
                }`}
              >
                {(notification.confidence * 100).toFixed(0)}%
              </span>
            </div>
          )}
          {notification.is_job_machine && (
            <div>
              <span className="text-xs text-gray-500 block">Source</span>
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                Job Machine
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Student Info */}
      {(notification.student_name || notification.student_username) && (
        <div>
          <h4 className="text-sm font-semibold text-gray-900 mb-2">Student</h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {notification.student_name && (
              <div>
                <span className="text-xs text-gray-500 block">Name</span>
                <span className="text-sm text-gray-900">{notification.student_name}</span>
              </div>
            )}
            {notification.student_username && (
              <div>
                <span className="text-xs text-gray-500 block">Username</span>
                <span className="text-sm text-gray-900">{notification.student_username}</span>
              </div>
            )}
            {notification.student_personal_email && (
              <div>
                <span className="text-xs text-gray-500 block">Personal Email</span>
                <span className="text-sm text-gray-900">{notification.student_personal_email}</span>
              </div>
            )}
            {notification.student_assigned_gmail && (
              <div>
                <span className="text-xs text-gray-500 block">Assigned Gmail</span>
                <span className="text-sm text-gray-900">{notification.student_assigned_gmail}</span>
              </div>
            )}
            {notification.student_phone && (
              <div>
                <span className="text-xs text-gray-500 block">Phone</span>
                <span className="text-sm text-gray-900">{notification.student_phone}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Email Notification */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-gray-900">Email Notification</h4>
          <div className="flex items-center space-x-2">
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${emailStatusStyle.bg} ${emailStatusStyle.text}`}>
              {notification.email_status}
            </span>
            {notification.auto_send_eligible && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 border border-green-200">
                Auto-send eligible
              </span>
            )}
          </div>
        </div>

        {notification.missing_fields && notification.missing_fields.length > 0 && (
          <div className="mb-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-800">
            Missing fields: {notification.missing_fields.join(', ')}
          </div>
        )}

        {isEditing ? (
          <div className="space-y-3 bg-white border border-gray-200 rounded-lg p-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Recipient</label>
              <input
                type="email"
                value={editRecipient}
                onChange={(e) => setEditRecipient(e.target.value)}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Subject</label>
              <input
                type="text"
                value={editSubject}
                onChange={(e) => setEditSubject(e.target.value)}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Body</label>
              <textarea
                rows={8}
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm font-mono"
              />
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => handleSaveAndSend(false)}
                disabled={editMutation.isPending}
                className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-200 disabled:opacity-50"
              >
                Save draft
              </button>
              <button
                onClick={() => setIsEditing(false)}
                className="px-3 py-1.5 border border-gray-300 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-500">
                To: <span className="text-gray-900">{notification.recipient_email || 'No recipient'}</span>
              </div>
              {notification.sent_at && (
                <div className="text-xs text-gray-500">
                  Sent: {format(new Date(notification.sent_at), 'MMM d, yyyy h:mm a')}
                </div>
              )}
            </div>
            <div className="text-sm font-medium text-gray-900">{notification.email_subject || 'No subject'}</div>
            <div className="text-sm text-gray-700 whitespace-pre-wrap max-h-48 overflow-y-auto border-t border-gray-100 pt-2">
              {notification.email_body || 'No body content'}
            </div>
            {notification.send_error && (
              <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-800">
                Error: {notification.send_error}
              </div>
            )}

            {isPending && (
              <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-gray-100">
                <Link to="/review" className="px-3 py-1.5 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700">
                  Approve or reject in Student notifications
                </Link>
                <button
                  onClick={() => startEditing(notification)}
                  className="px-3 py-1.5 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700"
                >
                  Edit draft
                </button>
              </div>
            )}

            {isSent && !isEditing && (
              <div className="pt-2 border-t border-gray-100">
                <span className="text-xs text-green-700">Notification sent successfully.</span>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Inbox content component - used in ReviewPage tabs
 */
const InboxContent = () => {
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const [expandedEmailId, setExpandedEmailId] = useState<number | null>(null);

  const { data: emails, isLoading, refetch } = useQuery({
    queryKey: showUnreadOnly ? ['unreadEmails'] : ['currentInbox'],
    queryFn: () =>
      showUnreadOnly
        ? apiClient.getUnreadEmails(false)
        : apiClient.getCurrentInbox(false),
  });

  const handleRefresh = async () => {
    await refetch();
  };

  const toggleExpand = (emailId: number) => {
    setExpandedEmailId(expandedEmailId === emailId ? null : emailId);
  };

  const isInterviewEmail = (email: Email): boolean => {
    return (email.latest_category || '').toLowerCase().includes('interview');
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end space-x-3">
        <button
          onClick={() => setShowUnreadOnly(!showUnreadOnly)}
          className={`px-4 py-2 rounded-md text-sm font-medium ${
            showUnreadOnly
              ? 'bg-primary-100 text-primary-700'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          {showUnreadOnly ? 'Show All' : 'Unread Only'}
        </button>
        <button
          onClick={handleRefresh}
          className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700"
        >
          Refresh
        </button>
      </div>

      {!emails || emails.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <p className="text-gray-500">No emails to display</p>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {emails.map((email) => {
              const isExpanded = expandedEmailId === email.id;
              const isInterview = isInterviewEmail(email);

              return (
                <li key={email.id}>
                  <div
                    className={`px-4 py-4 sm:px-6 cursor-pointer transition-colors ${
                      isExpanded ? 'bg-gray-50' : 'hover:bg-gray-50'
                    }`}
                    onClick={() => toggleExpand(email.id)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-3">
                          {!email.is_read && (
                            <div className="flex-shrink-0">
                              <div className="h-2 w-2 bg-blue-600 rounded-full"></div>
                            </div>
                          )}
                          <p className="text-sm font-medium text-gray-900 truncate">
                            {email.subject}
                          </p>
                          {isInterview && (
                            <span className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-purple-50 text-purple-700 border border-purple-200">
                              Interview
                            </span>
                          )}
                        </div>
                        <div className="mt-2 flex items-center text-sm text-gray-500">
                          <p className="truncate">From: {email.from_address}</p>
                        </div>
                        <div className="mt-2 flex items-center space-x-2">
                          <span className="text-xs text-gray-500">
                            {format(new Date(email.received_date), 'MMM d, yyyy h:mm a')}
                          </span>
                          {email.latest_category && (
                            <>
                              <span className="text-gray-300">&bull;</span>
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                                {email.latest_category}
                              </span>
                            </>
                          )}
                          {email.latest_confidence !== undefined && (
                            <>
                              <span className="text-gray-300">&bull;</span>
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                                  email.latest_confidence >= 0.7
                                    ? 'bg-green-100 text-green-800'
                                    : 'bg-orange-100 text-orange-800'
                                }`}
                              >
                                {(email.latest_confidence * 100).toFixed(0)}%
                              </span>
                            </>
                          )}
                          {email.latest_company && (
                            <>
                              <span className="text-gray-300">&bull;</span>
                              <span className="text-xs text-gray-600">
                                {email.latest_company}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center space-x-3 flex-shrink-0 ml-5">
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            email.current_folder === 'INBOX'
                              ? 'bg-gray-100 text-gray-800'
                              : 'bg-blue-100 text-blue-800'
                          }`}
                        >
                          {email.current_folder}
                        </span>
                        <svg
                          className={`h-5 w-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                          fill="none" viewBox="0 0 24 24" stroke="currentColor"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </div>
                    {!isExpanded && email.body_preview && (
                      <div className="mt-2">
                        <p className="text-sm text-gray-600 line-clamp-2">
                          {email.body_preview}
                        </p>
                      </div>
                    )}
                  </div>

                  {isExpanded && (
                    <div
                      className="border-t border-gray-200 bg-gray-50 px-6 py-4 space-y-4"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* Full email body */}
                      <EmailBodyPanel emailId={email.id} />

                      {/* Interview notification panel (interview emails only) */}
                      {isInterview && (
                        <div className="border-t border-gray-200 pt-4">
                          <InterviewDetailPanel emailId={email.id} />
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {emails && emails.length > 0 && (
        <div className="text-center text-sm text-gray-500">
          Showing {emails.length} email{emails.length !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
};

export default InboxContent;
