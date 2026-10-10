import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { TYPE_LABELS } from '../constants/interviewTypes';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import CountdownTimer from '../components/CountdownTimer';

const Skel = ({ w = 'w-16', h = 'h-8' }: { w?: string; h?: string }) => (
  <div className={`animate-pulse bg-gray-300 rounded ${w} ${h}`} />
);

const DashboardPage = () => {
  const queryClient = useQueryClient();
  const [runResult, setRunResult] = useState<{ status: string; message?: string } | null>(null);

  const runProcessingMutation = useMutation({
    mutationFn: () => apiClient.runProcessing(),
    onSuccess: (data) => {
      if (data?.status === 'error') {
        setRunResult({ status: 'error', message: data?.message || 'Processing failed.' });
        setTimeout(() => setRunResult(null), 8000);
        return;
      }
      if (data?.status === 'queued' || data?.status === 'locked') {
        // production: the server starts the run within a minute (or one is already running)
        setRunResult({ status: 'unavailable', message: data?.message || 'Run requested.' });
        setTimeout(() => setRunResult(null), 15000);
        return;
      }
      const count = data?.summary?.total_emails ?? data?.total_emails ?? 0;
      setRunResult({ status: 'success', message: `Done — ${count} emails processed.` });
      // Refresh all dashboard data
      queryClient.invalidateQueries({ queryKey: ['summaryStats'] });
      queryClient.invalidateQueries({ queryKey: ['processingRuns'] });
      queryClient.invalidateQueries({ queryKey: ['recentInterviews'] });
      queryClient.invalidateQueries({ queryKey: ['offers'] });
      queryClient.invalidateQueries({ queryKey: ['todayEmails'] });
      queryClient.invalidateQueries({ queryKey: ['upcomingInterviews'] });
      queryClient.invalidateQueries({ queryKey: ['reviewQueue'] });
      queryClient.invalidateQueries({ queryKey: ['inboxCount'] });
      setTimeout(() => setRunResult(null), 8000);
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || 'Check backend logs.';
      setRunResult({ status: 'error', message: `Processing failed: ${detail}` });
      setTimeout(() => setRunResult(null), 12000);
    },
  });

  // Convert UTC to CST (America/Chicago)
  const formatDateCST = (dateString: string) => {
    const utcString = dateString.endsWith('Z') || dateString.includes('+') ? dateString : dateString + 'Z';
    const date = new Date(utcString);
    const cstDate = toZonedTime(date, 'America/Chicago');
    return format(cstDate, 'MMM d, yyyy h:mm a');
  };

  // Stats and config queries
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['summaryStats'],
    queryFn: () => apiClient.getSummaryStats(),
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: 5 * 60 * 1000,
  });

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ['processingRuns'],
    queryFn: () => apiClient.getProcessingRuns(5),
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: 5 * 60 * 1000, // auto-refresh every 5 minutes
  });

  const { data: offers } = useQuery({
    queryKey: ['offers'],
    queryFn: () => apiClient.getOffers(100),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const { data: todayEmails, isLoading: todayEmailsLoading } = useQuery({
    queryKey: ['todayEmails'],
    queryFn: () => apiClient.getTodayEmails(),
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: 5 * 60 * 1000,
  });

  const { data: upcomingInterviews, isLoading: upcomingLoading } = useQuery({
    queryKey: ['upcomingInterviews'],
    queryFn: () => apiClient.getUpcomingInterviews(),
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: 5 * 60 * 1000,
  });

  const { data: reviewQueue, isLoading: queueLoading } = useQuery({
    queryKey: ['reviewQueue', false],
    queryFn: () => apiClient.getReviewQueue(false),
    staleTime: 0,
    refetchOnMount: 'always',
  });
  const upcomingWindowMs = 7 * 24 * 60 * 60 * 1000;
  const upcomingThisWeek = (upcomingInterviews ?? []).filter(
    (iv) => !!iv.interview_date && new Date(`${iv.interview_date}T23:59:59`).getTime() - Date.now() <= upcomingWindowMs,
  );
  const upcomingLater = (upcomingInterviews ?? []).length - upcomingThisWeek.length;
  const queueReady = reviewQueue ? reviewQueue.items.filter((i) => i.state === 'ready').length : 0;
  const queueFix = reviewQueue
    ? reviewQueue.items.filter((i) => ['needs_verification', 'blocked', 'needs_student', 'no_draft'].includes(i.state)).length
    : 0;



  const todayCST = format(toZonedTime(new Date(), 'America/Chicago'), 'yyyy-MM-dd');
  // Compare in Central time: received_date is UTC, so slicing it was a day off in the evening.
  const cstDay = (iso: string) => format(toZonedTime(new Date(iso), 'America/Chicago'), 'yyyy-MM-dd');
  const todayOffers = (offers ?? []).filter((offer: any) =>
    offer.received_date && cstDay(offer.received_date) === todayCST
  );

  // Trend arrow: today vs yesterday
  const todayCount = stats?.today_total_emails ?? 0;
  const yesterdayCount = stats?.yesterday_total_emails ?? 0;
  const emailTrendPct = yesterdayCount > 0
    ? Math.round(((todayCount - yesterdayCount) / yesterdayCount) * 100)
    : null;
  const lastRun = runs && runs.length > 0 ? runs[0] : null;

  return (
    <div className="space-y-6">
      {/* Page header: title centered, Run Now button right */}
      <div className="relative flex items-center justify-center py-2">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">AI-Inbox-Manager</h1>
          <p className="mt-1 text-sm text-gray-600">
            Command center for email processing and interview management
          </p>
        </div>
        {/* Next Processing Run — hidden */}
        <div className="absolute right-0 top-0 invisible">
          <CountdownTimer variant="nav" />
        </div>
        {/* Manual Run button — right side */}
        <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col items-end gap-1">
          <button
            onClick={() => { setRunResult(null); runProcessingMutation.mutate(); }}
            disabled={runProcessingMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-primary-400 text-white text-sm font-medium rounded-md shadow transition-colors"
          >
            <svg
              className={`h-4 w-4 ${runProcessingMutation.isPending ? 'animate-spin' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {runProcessingMutation.isPending ? 'Processing…' : 'Run Now'}
          </button>
          {runResult && (
            <span className={`text-xs font-medium px-2 py-1 rounded ${
              runResult.status === 'success'
                ? 'bg-green-100 text-green-800'
                : runResult.status === 'unavailable'
                ? 'bg-yellow-100 text-yellow-800'
                : 'bg-red-100 text-red-800'
            }`}>
              {runResult.message}
            </span>
          )}
        </div>
      </div>

      {/* Summary Stats Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {/* Emails Today — with optional Google Sheets audit subreport link */}
        {(() => {
          const sheetUrl = (import.meta.env.VITE_GOOGLE_SHEET_URL as string | undefined) || '';
          const inner = (
            <div className="p-5">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  <div className="text-3xl font-bold text-primary-600">
                    {statsLoading ? <Skel /> : stats?.today_total_emails || 0}
                  </div>
                </div>
                <div className="ml-5 w-0 flex-1">
                  <dl>
                    <dt className="text-sm font-bold text-gray-800 truncate">Emails Today</dt>
                    <dd className="mt-1 flex items-center gap-2">
                      {emailTrendPct !== null && (
                        <span className={`inline-flex items-center gap-0.5 text-xs font-semibold ${emailTrendPct >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {emailTrendPct >= 0 ? '↑' : '↓'}{Math.abs(emailTrendPct)}% vs yesterday
                        </span>
                      )}
                      {sheetUrl && (
                        <span className="inline-flex items-center gap-1 text-xs text-primary-600 font-medium">
                          View in Google Sheets
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                          </svg>
                        </span>
                      )}
                    </dd>
                  </dl>
                </div>
              </div>
            </div>
          );
          return sheetUrl ? (
            <a href={sheetUrl} target="_blank" rel="noopener noreferrer"
              className="bg-gray-200 overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow block"
              title="Open Google Sheets email audit log">
              {inner}
            </a>
          ) : (
            <div className="bg-gray-200 overflow-hidden shadow rounded-lg">{inner}</div>
          );
        })()}

        {/* Interview Requests */}
        <Link to="/reports?tab=interviews" className="bg-gray-200 overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="text-3xl font-bold text-green-600">
                  {statsLoading ? <Skel /> : stats?.today_interview_requests || 0}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">
                    Interview Requests Today
                  </dt>
                  <dd className="mt-1 text-xs text-primary-600">See all interviews in Reports</dd>
                </dl>
              </div>
            </div>
          </div>
        </Link>

        {/* Offers Received Today */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="text-3xl font-bold text-green-600">
                  {statsLoading ? <Skel /> : todayOffers.length}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">Offers Today</dt>
                  <dd className="mt-1 text-xs text-gray-500">Monthly goal is on Reports</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        {/* Last run: one line; the full history and system numbers are on Reports > System */}
        <Link to="/reports?tab=system" className="bg-gray-200 overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className={`text-3xl font-bold ${runsLoading || !lastRun ? 'text-gray-400' : lastRun.status === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                  {runsLoading ? <Skel /> : lastRun ? (lastRun.status === 'success' ? 'OK' : 'Failed') : '—'}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">Last run</dt>
                  <dd className="mt-1 text-xs text-gray-500 truncate">
                    {lastRun ? `${formatDateCST(lastRun.run_timestamp)} · ${lastRun.total_emails} emails` : 'No run yet'}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </Link>

      </div>

      {/* Quick Actions Banner */}
      {stats && stats.pending_approvals > 0 && (
        <div className="bg-orange-50 border-l-4 border-orange-400 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-orange-400"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm text-orange-700">
                You have <strong>{stats.pending_approvals}</strong> emails
                waiting for approval.{' '}
                <Link
                  to="/review?tab=approvals"
                  className="font-medium underline hover:text-orange-600"
                >
                  Review now
                </Link>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Upcoming Interviews: next 7 days, always shown so an empty list is explained */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 text-center">
          <h2 className="text-base font-bold text-gray-800">Upcoming Interviews (next 7 days)</h2>
          {upcomingLater > 0 && <p className="text-xs text-gray-500 mt-0.5">{upcomingLater} more later</p>}
        </div>
        <div className="px-4 py-5 sm:p-6">
          {upcomingLoading ? (
            <div className="space-y-2 py-2">
              {[...Array(3)].map((_, i) => <Skel key={i} w="w-full" h="h-8" />)}
            </div>
          ) : upcomingThisWeek.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Student</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Company</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Position</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Date</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Time</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Type</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Link</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {upcomingThisWeek.map((iv, idx) => {
                    const isToday = iv.interview_date === todayCST;
                    const isTomorrow = iv.interview_date === format(toZonedTime(new Date(Date.now() + 86400000), 'America/Chicago'), 'yyyy-MM-dd');
                    return (
                      <tr key={iv.interview_event_id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap">{iv.student_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-700 max-w-[160px] truncate">{iv.company_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-600 max-w-[160px] truncate">{iv.position || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {iv.interview_date ? (
                            <span className={`px-2 py-0.5 text-xs font-semibold rounded ${
                              isToday ? 'bg-red-100 text-red-700' :
                              isTomorrow ? 'bg-orange-100 text-orange-700' :
                              'bg-blue-50 text-blue-700'
                            }`}>
                              {isToday ? 'Today' : isTomorrow ? 'Tomorrow' : new Date(iv.interview_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-700 text-xs">{iv.interview_time || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-600 text-xs">{iv.interview_type ? TYPE_LABELS[iv.interview_type] || iv.interview_type : '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {iv.meeting_link ? (
                            <a href={iv.meeting_link} target="_blank" rel="noopener noreferrer"
                              className="text-xs text-primary-600 hover:underline font-medium">Join</a>
                          ) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">
              No interview has a confirmed date in the next 7 days. Requests that do not state a date yet are under Reports, Interviews tab.
            </p>
          )}
        </div>
      </div>

      {/* Needs your decision: replaces the old "Students Not Yet Notified" table; the details live in Review */}
      <Link
        to="/review"
        className="block bg-white shadow rounded-lg overflow-hidden border-l-4 border-blue-500 hover:bg-blue-50 transition-colors"
      >
        <div className="px-6 py-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-gray-800">Student notifications: needs your decision</h2>
            <p className="text-sm text-gray-600 mt-1">
              {queueLoading || !reviewQueue
                ? 'Loading...'
                : `${queueReady} ready to approve or reject, ${queueFix} need fixing first (no student matched, or no way to reach them).${(reviewQueue.callbacks ?? []).length ? ` ${reviewQueue.callbacks.length} student(s) called back and are waiting for a callback.` : ''}`}
            </p>
          </div>
          <span className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium">Open the approval screen</span>
        </div>
      </Link>

      {/* Emails Processed Today — hidden when empty */}
      {(todayEmailsLoading || (todayEmails && todayEmails.length > 0)) && (
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-800 flex-1 text-center">Emails Processed Today</h2>
        </div>
        <div className="px-4 py-5 sm:p-6">
          {todayEmailsLoading ? (
            <div className="space-y-2 py-4">
              {[...Array(4)].map((_, i) => <Skel key={i} w="w-full" h="h-6" />)}
            </div>
          ) : todayEmails && todayEmails.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Time (CST)</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Subject</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">From</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Category</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Company</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Folder</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {todayEmails.map((email: any, idx: number) => (
                    <tr key={email.id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700 text-xs">
                        {email.fetch_timestamp ? formatDateCST(email.fetch_timestamp) : '—'}
                      </td>
                      <td className="px-3 py-2 text-gray-900 max-w-[220px] truncate" title={email.subject || ''}>{email.subject || '—'}</td>
                      <td className="px-3 py-2 text-gray-600 max-w-[180px] truncate" title={email.from_address || ''}>{email.from_address || '—'}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={`px-2 py-0.5 text-xs font-medium rounded ${
                          /^(Offer|Offers)$/.test(email.category || '') ? 'bg-green-100 text-green-800' :
                          /^(Rejection|Rejections)$/.test(email.category || '') ? 'bg-red-100 text-red-800' :
                          /Interview|Screen/.test(email.category || '') ? 'bg-blue-100 text-blue-800' :
                          'bg-gray-100 text-gray-700'
                        }`}>
                          {email.category || '—'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-gray-700 max-w-[140px] truncate" title={email.company_name || ''}>{email.company_name || '—'}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-500 text-xs">{email.current_folder || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">No emails processed today</p>
          )}
        </div>
      </div>
      )}

    </div>
  );
};

export default DashboardPage;
