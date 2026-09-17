import { useState, Fragment } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line } from 'recharts';
import CountdownTimer from '../components/CountdownTimer';
import InterviewChecklist from '../components/InterviewChecklist';
import type { InterviewRequest } from '../types';

const Skel = ({ w = 'w-16', h = 'h-8' }: { w?: string; h?: string }) => (
  <div className={`animate-pulse bg-gray-300 rounded ${w} ${h}`} />
);

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

const DashboardPage = () => {
  const queryClient = useQueryClient();
  const [expandedInterviewId, setExpandedInterviewId] = useState<number | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [runResult, setRunResult] = useState<{ status: string; message?: string } | null>(null);

  const runProcessingMutation = useMutation({
    mutationFn: () => apiClient.runProcessing(),
    onSuccess: (data) => {
      if (data?.status === 'error') {
        setRunResult({ status: 'error', message: data?.message || 'Processing failed.' });
        setTimeout(() => setRunResult(null), 8000);
        return;
      }
      if (data?.status === 'unavailable') {
        setRunResult({ status: 'unavailable', message: 'Run Now is local-only. Trigger manually on your machine.' });
        setTimeout(() => setRunResult(null), 10000);
        return;
      }
      const count = data?.summary?.total_emails ?? data?.total_emails ?? 0;
      setRunResult({ status: 'success', message: `Done — ${count} emails processed.` });
      // Refresh all dashboard data
      queryClient.invalidateQueries({ queryKey: ['summaryStats'] });
      queryClient.invalidateQueries({ queryKey: ['processingRuns'] });
      queryClient.invalidateQueries({ queryKey: ['categoryBreakdown'] });
      queryClient.invalidateQueries({ queryKey: ['trends'] });
      queryClient.invalidateQueries({ queryKey: ['recentInterviews'] });
      queryClient.invalidateQueries({ queryKey: ['offers'] });
      queryClient.invalidateQueries({ queryKey: ['todayEmails'] });
      queryClient.invalidateQueries({ queryKey: ['upcomingInterviews'] });
      queryClient.invalidateQueries({ queryKey: ['missedNotifications'] });
      queryClient.invalidateQueries({ queryKey: ['inboxCount'] });
      queryClient.invalidateQueries({ queryKey: ['engineeringKPIs'] });
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

  // Recent interviews (limit to 5)
  const { data: interviews, isLoading: interviewsLoading } = useQuery({
    queryKey: ['recentInterviews'],
    queryFn: () => apiClient.getInterviewRequests(5, 0),
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: 5 * 60 * 1000,
  });

  // Inbox count with sync capability
  const { data: inboxCount, refetch: refetchInboxCount } = useQuery({
    queryKey: ['inboxCount'],
    queryFn: () => apiClient.getInboxCount(false),
    staleTime: 0,
  });

  // Stats charts data
  const { data: categoryData } = useQuery({
    queryKey: ['categoryBreakdown'],
    queryFn: () => apiClient.getCategoryBreakdown(new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)),
  });

  const { data: trends } = useQuery({
    queryKey: ['trends'],
    queryFn: () => apiClient.getTrends(7),
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

  const { data: missedNotifications, isLoading: missedLoading } = useQuery({
    queryKey: ['missedNotifications'],
    queryFn: () => apiClient.getMissedInterviews(),
    staleTime: 0,
    refetchOnMount: 'always',
  });



  const todayCST = format(toZonedTime(new Date(), 'America/Chicago'), 'yyyy-MM-dd');
  const todayOffers = (offers ?? []).filter((offer: any) =>
    offer.received_date && offer.received_date.slice(0, 10) === todayCST
  );

  // Trend arrow: today vs yesterday
  const todayCount = stats?.today_total_emails ?? 0;
  const yesterdayCount = stats?.yesterday_total_emails ?? 0;
  const emailTrendPct = yesterdayCount > 0
    ? Math.round(((todayCount - yesterdayCount) / yesterdayCount) * 100)
    : null;

  // Offers progress bar (monthly goal = 10)
  const OFFER_GOAL = 10;
  const currentMonthOffers = (offers ?? []).filter((o: any) => {
    if (!o.received_date) return false;
    const d = new Date(o.received_date);
    const now = new Date();
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
  }).length;

  // Sparkline data for This Week card
  const sparklineData = (trends?.trends ?? []).slice(-7).map((d: any) => ({ v: d.total_emails }));

  const { data: engKPIs } = useQuery({
    queryKey: ['engineeringKPIs'],
    queryFn: () => apiClient.getEngineeringKPIs(),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const handleSyncInbox = async () => {
    setIsSyncing(true);
    try {
      await apiClient.getInboxCount(true);
      await refetchInboxCount();
      queryClient.invalidateQueries({ queryKey: ['summaryStats'] });
    } finally {
      setIsSyncing(false);
    }
  };

  const toggleInterviewExpand = (interviewId: number) => {
    setExpandedInterviewId(expandedInterviewId === interviewId ? null : interviewId);
  };

  const getTypeStyle = (interviewType?: string) => {
    if (!interviewType) return 'bg-gray-100 text-gray-800';
    return TYPE_STYLES[interviewType] || 'bg-gray-100 text-gray-800';
  };

  const getTypeLabel = (interviewType?: string) => {
    if (!interviewType) return 'N/A';
    return TYPE_LABELS[interviewType] || interviewType;
  };

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
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5">
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
        <Link to="/interviews" className="bg-gray-200 overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="text-3xl font-bold text-green-600">
                  {statsLoading ? <Skel /> : stats?.total_interview_requests || 0}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">
                    Interview Requests
                  </dt>
                  <dd className="mt-1 text-xs text-primary-600">Click to view all</dd>
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
                  <dt className="text-sm font-bold text-gray-800 truncate">Offers Received</dt>
                  <dd className="mt-1 text-xs text-gray-500">{currentMonthOffers}/{OFFER_GOAL} this month</dd>
                </dl>
              </div>
            </div>
            <div className="mt-2">
              <div className="w-full bg-gray-300 rounded-full h-1.5">
                <div
                  className="bg-green-500 h-1.5 rounded-full transition-all"
                  style={{ width: `${Math.min((currentMonthOffers / OFFER_GOAL) * 100, 100)}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* This Week */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  <div className="text-3xl font-bold text-gray-600">
                    {statsLoading ? <Skel /> : stats?.week_total_emails || 0}
                  </div>
                </div>
                <div className="ml-4">
                  <dt className="text-sm font-bold text-gray-800">This Week</dt>
                </div>
              </div>
              {sparklineData.length > 1 && (
                <ResponsiveContainer width={70} height={36}>
                  <LineChart data={sparklineData}>
                    <Line type="monotone" dataKey="v" stroke="#6b7280" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </div>

        {/* Inbox Count with Sync */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  <div className="text-3xl font-bold text-blue-600">
                    {statsLoading ? <Skel /> : inboxCount?.count ?? stats?.inbox_count ?? 0}
                  </div>
                </div>
                <div className="ml-4">
                  <dt className="text-sm font-bold text-gray-800">
                    In Inbox
                  </dt>
                </div>
              </div>
              <button
                onClick={handleSyncInbox}
                disabled={isSyncing}
                className="p-2 text-gray-400 hover:text-primary-600 transition-colors disabled:opacity-50"
                title="Sync from IMAP"
              >
                <svg
                  className={`h-5 w-5 ${isSyncing ? 'animate-spin' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                  />
                </svg>
              </button>
            </div>
            {inboxCount?.synced && (
              <div className="mt-1 text-xs text-green-600">Live synced</div>
            )}
          </div>
        </div>
      </div>

      {/* Quick Reports — full width */}
      <Link
        to="/interview-events"
        className="block w-full overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow group"
        style={{ backgroundColor: 'rgba(209,213,219,0.4)' }}
      >
        <div className="p-5 flex items-center gap-4">
          <div className="flex-shrink-0 p-3 bg-indigo-100 rounded-full group-hover:bg-indigo-200 transition-colors">
            <svg className="h-6 w-6 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-800 group-hover:text-indigo-700 transition-colors">
              Interview Events Report
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              View all interview events with student notification status
            </p>
          </div>
          <svg className="h-5 w-5 text-gray-300 group-hover:text-indigo-400 ml-auto transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </Link>

      {/* Engineering KPIs */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-4">
        {/* AI Cost Today */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="text-3xl font-bold text-emerald-600">
                  {engKPIs == null ? <Skel /> : `$${engKPIs.ai_cost_today_usd.toFixed(4)}`}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">AI Cost Today</dt>
                  <dd className="mt-1 text-xs text-gray-500">GPT spend since midnight UTC</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        {/* Avg Processing Duration (7-day) */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="text-3xl font-bold text-blue-600">
                  {engKPIs == null ? <Skel /> : engKPIs.avg_duration_seconds_7d != null ? `${engKPIs.avg_duration_seconds_7d}s` : '—'}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">Avg Duration (7d)</dt>
                  <dd className="mt-1 text-xs text-gray-500">
                    {engKPIs ? `over ${engKPIs.run_count_7d} run${engKPIs.run_count_7d !== 1 ? 's' : ''}` : 'rolling average'}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        {/* Failure Rate (7-day) */}
        <div className="bg-gray-200 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className={`text-3xl font-bold ${
                  engKPIs == null ? 'text-gray-400'
                  : engKPIs.failure_rate_7d === 0 ? 'text-green-600'
                  : engKPIs.failure_rate_7d < 20 ? 'text-yellow-600'
                  : 'text-red-600'
                }`}>
                  {engKPIs != null ? `${engKPIs.failure_rate_7d}%` : '—'}
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-bold text-gray-800 truncate">Failure Rate (7d)</dt>
                  <dd className="mt-1 text-xs text-gray-500">
                    {engKPIs
                      ? `${engKPIs.failed_run_count_7d} of ${engKPIs.run_count_7d} runs failed`
                      : 'last 7 days'}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Charts: Category Breakdown + Daily Trends — directly under stat cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Category Breakdown Donut Chart */}
        {(() => {
          const ALLOWED_CATEGORIES = [
            'Offer',
            'Rejection',
            'Interview Request',
            'Interview Schedule',
            'Interview Confirmation',
          ];
          const CATEGORY_COLORS: Record<string, string> = {
            'Offer':                  '#22c55e',  // green
            'Rejection':              '#dc2626',  // red
            'Interview Request':      '#2563eb',  // blue
            'Interview Schedule':     '#f97316',  // orange
            'Interview Confirmation': '#8b5cf6',  // purple
          };
          const filteredCategoryData = (categoryData ?? []).filter(d => ALLOWED_CATEGORIES.includes(d.category));
          const total = filteredCategoryData.reduce((sum, d) => sum + d.count, 0);
          return (
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="bg-gray-200 px-6 py-3 text-center">
                <h2 className="text-base font-bold text-gray-800">Category Breakdown (Last 30 Days)</h2>
              </div>
              <div className="p-6">
                {filteredCategoryData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie
                        data={filteredCategoryData}
                        dataKey="count"
                        nameKey="category"
                        cx="50%"
                        cy="50%"
                        innerRadius={65}
                        outerRadius={100}
                        paddingAngle={3}
                      >
                        {filteredCategoryData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={CATEGORY_COLORS[entry.category] ?? '#6b7280'} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value: number) => [`${value} (${((value / total) * 100).toFixed(1)}%)`, 'Count']} />
                      <Legend
                        iconType="circle"
                        iconSize={10}
                        formatter={(value) => <span style={{ fontSize: 11 }}>{value}</span>}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex flex-col items-center justify-center h-64 text-gray-400">
                    <svg className="h-12 w-12 mb-3 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
                    </svg>
                    <p className="text-sm font-medium">No category data available</p>
                    <p className="text-xs mt-1">Data will appear after emails are processed</p>
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {/* Daily Trends */}
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 text-center">
            <h2 className="text-base font-bold text-gray-800">Daily Trends (Last 7 Days)</h2>
          </div>
          <div className="p-6">
            {trends && trends.trends && trends.trends.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={trends.trends}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" fontSize={11} />
                  <YAxis fontSize={11} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                  <Bar dataKey="total_emails" fill="#3b82f6" name="Total" />
                  <Bar dataKey="interview_requests" fill="#10b981" name="Interviews" />
                  <Bar dataKey="spam_deleted" fill="#ef4444" name="Deleted" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-gray-400">
                <svg className="h-12 w-12 mb-3 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <p className="text-sm font-medium">No trend data available</p>
                <p className="text-xs mt-1">Data will appear after emails are processed</p>
              </div>
            )}
          </div>
        </div>
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
                  to="/review"
                  className="font-medium underline hover:text-orange-600"
                >
                  Review now
                </Link>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Upcoming Interviews This Week — hidden when empty */}
      {(upcomingLoading || (upcomingInterviews && upcomingInterviews.length > 0)) && (
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 text-center">
          <h2 className="text-base font-bold text-gray-800">Upcoming Interviews This Week</h2>
        </div>
        <div className="px-4 py-5 sm:p-6">
          {upcomingLoading ? (
            <div className="space-y-2 py-2">
              {[...Array(3)].map((_, i) => <Skel key={i} w="w-full" h="h-8" />)}
            </div>
          ) : upcomingInterviews && upcomingInterviews.length > 0 ? (
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
                  {upcomingInterviews.map((iv, idx) => {
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
            <p className="text-sm text-gray-500 text-center py-8">No upcoming interviews scheduled</p>
          )}
        </div>
      </div>
      )}

      {/* Students Not Yet Notified */}
      {(missedLoading || (missedNotifications && missedNotifications.length > 0)) && (
        <div className="bg-white shadow rounded-lg overflow-hidden border-l-4 border-orange-400">
          <div className="bg-orange-50 px-6 py-3 flex items-center gap-2">
            <svg className="h-5 w-5 text-orange-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <h2 className="text-base font-bold text-orange-800">
              Students Not Yet Notified
              {!missedLoading && missedNotifications && (
                <span className="ml-2 px-2 py-0.5 bg-orange-200 text-orange-900 text-xs rounded-full">{missedNotifications.length}</span>
              )}
            </h2>
          </div>
          <div className="px-4 py-5 sm:p-6">
            {missedLoading ? (
              <div className="space-y-2 py-2">
                {[...Array(3)].map((_, i) => <Skel key={i} w="w-full" h="h-8" />)}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead>
                    <tr className="bg-gray-50">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Student</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Company</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Position</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Received</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(missedNotifications ?? []).map((item: any, idx: number) => (
                      <tr key={item.email_id} className={idx % 2 === 0 ? 'bg-white' : 'bg-orange-50'}>
                        <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap">{item.student_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-700 max-w-[160px] truncate" title={item.company_name}>{item.company_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-600 max-w-[160px] truncate" title={item.position}>{item.position || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-500">
                          {item.received_date ? formatDateCST(item.received_date) : '—'}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className="px-2 py-0.5 text-xs font-medium rounded bg-orange-100 text-orange-800">
                            {item.notification_status === 'not_created' ? 'Not created' : item.notification_status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

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
                          email.category === 'Interview Request' ? 'bg-blue-100 text-blue-800' :
                          email.category === 'Offer' ? 'bg-green-100 text-green-800' :
                          email.category === 'Rejection' ? 'bg-red-100 text-red-800' :
                          email.category === 'Interview Schedule' ? 'bg-orange-100 text-orange-800' :
                          email.category === 'Interview Confirmation' ? 'bg-purple-100 text-purple-800' :
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

      {/* Two-column layout: Recent Interviews + Recent Runs */}
      <div className={`grid grid-cols-1 gap-6 ${interviewsLoading || (interviews && interviews.length > 0) ? 'lg:grid-cols-2' : ''}`}>
        {/* Recent Interviews — hidden when empty */}
        {(interviewsLoading || (interviews && interviews.length > 0)) && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-800 flex-1 text-center">Recent Interview Requests</h2>
            <Link
              to="/interviews"
              className="text-sm text-primary-600 hover:text-primary-700 font-medium ml-4"
            >
              View all
            </Link>
          </div>
          <div className="px-4 py-5 sm:p-6">
            {interviewsLoading ? (
              <div className="space-y-2 py-4">
                {[...Array(3)].map((_, i) => <Skel key={i} w="w-full" h="h-12" />)}
              </div>
            ) : interviews && interviews.length > 0 ? (
              <>
                {/* Mini pie chart — type breakdown */}
                {(() => {
                  const TYPE_COLORS: Record<string, string> = {
                    'interview_request': '#3b82f6',
                    'phone_screen': '#10b981',
                    'client_screen': '#8b5cf6',
                    'technical_interview': '#f59e0b',
                    'cancelled': '#ef4444',
                    'rescheduled': '#f97316',
                    'job_machine': '#6366f1',
                  };
                  const counts: Record<string, number> = {};
                  interviews.forEach((iv: InterviewRequest) => {
                    const key = iv.interview_type || 'unknown';
                    counts[key] = (counts[key] || 0) + 1;
                  });
                  const pieData = Object.entries(counts).map(([key, value]) => ({
                    name: TYPE_LABELS[key] || key,
                    value,
                    color: TYPE_COLORS[key] || '#9ca3af',
                  }));
                  return (
                    <div className="mb-4">
                      <ResponsiveContainer width="100%" height={160}>
                        <PieChart>
                          <Pie
                            data={pieData}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            innerRadius={40}
                            outerRadius={65}
                            paddingAngle={3}
                          >
                            {pieData.map((entry, index) => (
                              <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                          </Pie>
                          <Tooltip formatter={(value: number) => [`${value}`, 'Requests']} />
                          <Legend iconType="circle" iconSize={9} formatter={(value) => <span style={{ fontSize: 11 }}>{value}</span>} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  );
                })()}

                {/* Interview list */}
                <div className="space-y-3">
                  {interviews.map((interview: InterviewRequest) => {
                    const isExpanded = expandedInterviewId === interview.id;
                    return (
                      <Fragment key={interview.id}>
                        <div
                          className={`border rounded-lg transition-colors cursor-pointer ${
                            isExpanded ? 'border-primary-300 bg-primary-50' : 'border-gray-200 hover:bg-gray-50'
                          }`}
                          onClick={() => toggleInterviewExpand(interview.id)}
                        >
                          <div className="p-3">
                            <div className="flex items-center justify-between">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center space-x-2">
                                  <span className="text-sm font-medium text-gray-900 truncate">
                                    {interview.student_name || 'Unknown Student'}
                                  </span>
                                  <span className={`px-2 py-0.5 text-xs font-medium rounded ${getTypeStyle(interview.interview_type)}`}>
                                    {getTypeLabel(interview.interview_type)}
                                  </span>
                                </div>
                                <div className="mt-1 flex items-center space-x-2 text-xs text-gray-500">
                                  <span>{interview.company_name || 'Unknown Company'}</span>
                                  {interview.position && (
                                    <>
                                      <span>&bull;</span>
                                      <span>{interview.position}</span>
                                    </>
                                  )}
                                </div>
                                <div className="mt-1 flex items-center space-x-3 text-xs text-gray-400">
                                  <span>Received: {formatDateCST(interview.received_date)}</span>
                                  {interview.interview_date && (
                                    <span className="text-primary-600 font-medium">
                                      Interview: {new Date(interview.interview_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                                      {interview.interview_time && ` at ${interview.interview_time}`}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <svg
                                className={`h-5 w-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                              >
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                              </svg>
                            </div>
                          </div>
                        </div>
                        {isExpanded && (
                          <div onClick={(e) => e.stopPropagation()} className="-mt-2 mb-1">
                            {interview.interview_event_id ? (
                              <InterviewChecklist interviewEventId={interview.interview_event_id} />
                            ) : (
                              <div className="border border-t-0 border-gray-200 rounded-b-lg bg-gray-50 px-4 py-3 text-sm text-gray-500">
                                No checklist available. This interview has not been sub-classified yet.
                              </div>
                            )}
                          </div>
                        )}
                      </Fragment>
                    );
                  })}
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-500 text-center py-8">No recent interview requests</p>
            )}
          </div>
        </div>
        )}

        {/* Recent Processing Runs */}
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 text-center">
            <h2 className="text-base font-bold text-gray-800">Recent Processing Runs</h2>
          </div>
          <div className="px-4 py-5 sm:p-6">
            {runsLoading ? (
              <div className="space-y-2 py-4">
                {[...Array(3)].map((_, i) => <Skel key={i} w="w-full" h="h-8" />)}
              </div>
            ) : runs && runs.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead>
                    <tr className="bg-gray-50">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Date / Time (CST)</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">Emails</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">Interviews</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">Organized</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">Deleted</th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {runs.map((run, idx) => (
                      <tr key={run.id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-900 font-medium">
                          {formatDateCST(run.run_timestamp)}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-700">{run.total_emails}</td>
                        <td className="px-3 py-2 text-right font-semibold text-green-600">{run.interview_requests}</td>
                        <td className="px-3 py-2 text-right text-gray-700">{run.organized}</td>
                        <td className="px-3 py-2 text-right text-red-600">{run.spam_deleted}</td>
                        <td className="px-3 py-2 text-center">
                          <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                            run.status === 'success'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}>
                            {run.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-gray-500 text-center py-8">No recent processing runs</p>
            )}
          </div>
        </div>
      </div>

    </div>
  );
};

export default DashboardPage;
