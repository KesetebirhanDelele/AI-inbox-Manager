import { useState, Fragment, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import InterviewChecklist from '../components/InterviewChecklist';
import type { InterviewEventRecord, UpcomingInterview } from '../types';

const TYPE_STYLES: Record<string, string> = {
  'interview_request': 'bg-blue-100 text-blue-800',
  'phone_screen': 'bg-green-100 text-green-800',
  'client_screen': 'bg-purple-100 text-purple-800',
  'technical_interview': 'bg-yellow-100 text-yellow-800',
  'cancelled': 'bg-red-100 text-red-800',
  'rescheduled': 'bg-orange-100 text-orange-800',
  'job_machine': 'bg-indigo-100 text-indigo-800',
};

const TYPE_LABELS: Record<string, string> = {
  'interview_request': 'Interview Request',
  'phone_screen': 'Phone Screen',
  'client_screen': 'Client Screen',
  'technical_interview': 'Technical Interview',
  'cancelled': 'Cancelled',
  'rescheduled': 'Rescheduled',
  'job_machine': 'Job Machine',
};

const NOTIF_STYLES: Record<string, string> = {
  sent: 'bg-green-100 text-green-800',
  approved: 'bg-blue-100 text-blue-800',
  draft: 'bg-yellow-100 text-yellow-800',
  failed: 'bg-red-100 text-red-800',
  rejected: 'bg-gray-100 text-gray-600',
};

const NOTIF_LABELS: Record<string, string> = {
  sent: 'Notified',
  approved: 'Approved',
  draft: 'Needs your decision',
  failed: 'Send failed',
  rejected: 'Rejected',
};

type FilterTab = 'all' | 'decision' | 'notified' | 'cannot';

const PAGE_SIZE = 25;
const DAY_MS = 24 * 60 * 60 * 1000;

/** "Notified", "Needs your decision", or why there is nothing to notify yet. */
const notificationOf = (e: InterviewEventRecord): { label: string; cls: string; decide: boolean } => {
  if (e.notification_status) {
    return {
      label: NOTIF_LABELS[e.notification_status] || e.notification_status,
      cls: NOTIF_STYLES[e.notification_status] || 'bg-gray-100 text-gray-700',
      decide: e.notification_status === 'draft',
    };
  }
  if (!e.student_name || e.student_name === 'Unknown') {
    return { label: 'Student not identified', cls: 'bg-red-100 text-red-800', decide: false };
  }
  return { label: 'No draft', cls: 'bg-gray-100 text-gray-700', decide: false };
};

const InterviewsPage = () => {
  const [expandedEventId, setExpandedEventId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [activeTab, setActiveTab] = useState<FilterTab>('all');
  const [currentPage, setCurrentPage] = useState(0);

  const { data: events, isLoading } = useQuery({
    queryKey: ['interviewEvents'],
    queryFn: () => apiClient.getInterviewEvents(),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const { data: upcomingInterviews } = useQuery({
    queryKey: ['upcomingInterviews'],
    queryFn: () => apiClient.getUpcomingInterviews(),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const formatDateCST = (dateString: string) => {
    const utcString = dateString.endsWith('Z') || dateString.includes('+') ? dateString : dateString + 'Z';
    const date = new Date(utcString);
    const cstDate = toZonedTime(date, 'America/Chicago');
    return format(cstDate, 'MMM d, yyyy h:mm a');
  };

  const getTypeStyle = (t?: string) => (t ? TYPE_STYLES[t] || 'bg-gray-100 text-gray-800' : 'bg-gray-100 text-gray-800');
  const getTypeLabel = (t?: string) => (t ? TYPE_LABELS[t] || t : 'N/A');

  const counts = useMemo(() => {
    const all = events ?? [];
    return {
      all: all.length,
      decision: all.filter((e) => e.notification_status === 'draft').length,
      notified: all.filter((e) => e.notification_status === 'sent').length,
      cannot: all.filter((e) => !e.notification_status).length,
    };
  }, [events]);

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return (events ?? []).filter((e: InterviewEventRecord) => {
      if (activeTab === 'decision' && e.notification_status !== 'draft') return false;
      if (activeTab === 'notified' && e.notification_status !== 'sent') return false;
      if (activeTab === 'cannot' && e.notification_status) return false;
      const matchesSearch =
        !q ||
        (e.student_name || '').toLowerCase().includes(q) ||
        (e.company_name || '').toLowerCase().includes(q) ||
        (e.position_title || '').toLowerCase().includes(q) ||
        (e.subject || '').toLowerCase().includes(q);
      const matchesType = !typeFilter || e.interview_type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [events, searchQuery, typeFilter, activeTab]);

  // Upcoming: interviews with a confirmed date in the next 7 days; later ones are counted, not hidden.
  const { thisWeek, later } = useMemo(() => {
    const now = Date.now();
    const soon: UpcomingInterview[] = [];
    let after = 0;
    for (const iv of upcomingInterviews ?? []) {
      const t = iv.interview_date ? new Date(`${iv.interview_date}T23:59:59`).getTime() : NaN;
      if (Number.isNaN(t)) continue;
      if (t - now <= 7 * DAY_MS) soon.push(iv);
      else after += 1;
    }
    return { thisWeek: soon, later: after };
  }, [upcomingInterviews]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const resetView = () => {
    setCurrentPage(0);
    setExpandedEventId(null);
  };

  const tabs: { id: FilterTab; name: string; count: number }[] = [
    { id: 'all', name: 'All', count: counts.all },
    { id: 'decision', name: 'Needs your decision', count: counts.decision },
    { id: 'notified', name: 'Notified', count: counts.notified },
    { id: 'cannot', name: 'Not notified yet', count: counts.cannot },
  ];

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Interviews</h1>
        <p className="mt-1 text-sm text-gray-600">
          Every interview found in the inbox, with its student and notification status. Click a row to see the process
          checklist. Approve or reject student notifications under Review.
        </p>
      </div>

      {/* Upcoming interviews: always shown, so an empty list is explained */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-800">Upcoming interviews (next 7 days)</h2>
          {later > 0 && <span className="text-xs text-gray-600">{later} more later</span>}
        </div>
        <div className="px-4 py-4 sm:p-6">
          {thisWeek.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    {['Student', 'Company', 'Position', 'Date', 'Time', 'Format'].map((h) => (
                      <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {thisWeek.map((iv) => (
                    <tr key={iv.interview_event_id}>
                      <td className="px-3 py-2 font-medium text-gray-900">{iv.student_name || 'Unknown'}</td>
                      <td className="px-3 py-2 text-gray-700">{iv.company_name || '—'}</td>
                      <td className="px-3 py-2 text-gray-600">{iv.position || '—'}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{iv.interview_date}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{[iv.interview_time, iv.interview_timezone].filter(Boolean).join(' ') || '—'}</td>
                      <td className="px-3 py-2 capitalize">{iv.interview_format || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">
              No interview has a confirmed date in the next 7 days. Interview requests that do not state a date yet appear
              in the list below.
            </p>
          )}
        </div>
      </div>

      {/* All interviews */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 mb-4">
            <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    setActiveTab(t.id);
                    resetView();
                  }}
                  className={`px-3 py-1.5 text-sm rounded-md ${
                    activeTab === t.id ? 'bg-white shadow text-gray-900 font-medium' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {t.name} <span className="text-xs text-gray-500">({t.count})</span>
                </button>
              ))}
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                placeholder="Search student, company, position…"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  resetView();
                }}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 w-64"
              />
              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value);
                  resetView();
                }}
                className="py-1.5 pl-3 pr-8 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
              >
                <option value="">All Types</option>
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>

          {paginated.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-3 w-8"></th>
                      {['Student', 'Type', 'Company', 'Position', 'Interview date', 'Received', 'Notification'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {paginated.map((e: InterviewEventRecord) => {
                      const isExpanded = expandedEventId === e.event_id;
                      const notif = notificationOf(e);
                      return (
                        <Fragment key={e.event_id}>
                          <tr
                            className={`cursor-pointer transition-colors ${isExpanded ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                            onClick={() => setExpandedEventId(isExpanded ? null : e.event_id)}
                          >
                            <td className="px-3 py-4 whitespace-nowrap">
                              <svg
                                className={`h-5 w-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                fill="none" viewBox="0 0 24 24" stroke="currentColor"
                              >
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                              </svg>
                            </td>
                            <td className="px-4 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                              {e.student_name || 'Unknown'}
                              {e.student_email && <div className="text-xs font-normal text-gray-500">{e.student_email}</div>}
                            </td>
                            <td className="px-4 py-4 whitespace-nowrap">
                              <span className={`px-2 py-1 text-xs font-medium rounded ${getTypeStyle(e.interview_type)}`}>
                                {getTypeLabel(e.interview_type)}
                              </span>
                            </td>
                            <td className="px-4 py-4 text-sm text-gray-900">{e.company_name || '-'}</td>
                            <td className="px-4 py-4 text-sm text-gray-900">{e.position_title || '-'}</td>
                            <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-700">
                              {e.interview_date
                                ? [e.interview_date, e.interview_time, e.interview_timezone].filter(Boolean).join(' ')
                                : <span className="text-gray-400">Not scheduled yet</span>}
                            </td>
                            <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                              {e.received_date ? formatDateCST(e.received_date) : '—'}
                            </td>
                            <td className="px-4 py-4 whitespace-nowrap">
                              <span className={`px-2 py-1 text-xs font-medium rounded ${notif.cls}`}>{notif.label}</span>
                              {notif.decide && (
                                <Link
                                  to="/review"
                                  onClick={(ev) => ev.stopPropagation()}
                                  className="ml-2 text-xs text-primary-600 hover:underline"
                                >
                                  Decide
                                </Link>
                              )}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr>
                              <td colSpan={9} className="p-0">
                                <div onClick={(ev) => ev.stopPropagation()}>
                                  {e.subject && (
                                    <div className="border-t border-gray-200 bg-gray-50 px-6 py-3 text-sm text-gray-700">
                                      <span className="text-xs text-gray-500">Email: </span>
                                      {e.subject}
                                      {e.from_address && <span className="text-xs text-gray-500"> from {e.from_address}</span>}
                                    </div>
                                  )}
                                  <InterviewChecklist interviewEventId={e.event_id} />
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between border-t border-gray-200 pt-4">
                  <p className="text-sm text-gray-500">
                    Showing {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
                  </p>
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                      disabled={currentPage === 0}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Previous
                    </button>
                    <span className="text-sm text-gray-600">Page {currentPage + 1} of {totalPages}</span>
                    <button
                      type="button"
                      onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
                      disabled={currentPage === totalPages - 1}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12">
              <h3 className="text-sm font-medium text-gray-900">
                {searchQuery || typeFilter || activeTab !== 'all' ? 'No interviews match' : 'No interviews yet'}
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                {searchQuery || typeFilter || activeTab !== 'all'
                  ? 'Try another tab, search or type.'
                  : 'Interview emails will appear here after the next processing run.'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default InterviewsPage;
