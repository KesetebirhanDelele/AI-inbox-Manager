import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { apiClient } from '../api/client';
import InterviewsPage from './InterviewsPage';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'interviews', label: 'Interviews' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'students', label: 'Students' },
  { id: 'companies', label: 'Companies' },
  { id: 'system', label: 'System' },
];

// Sizes under 1 GB stay in MB; larger caps (the Hetzner disk budget) read better in GB.
const formatStorage = (bytes: number | null | undefined): string => {
  const mb = (bytes ?? 0) / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(mb < 100 ? 1 : 0)} MB`;
};

const PALETTE = ['#2563eb', '#16a34a', '#dc2626', '#f97316', '#8b5cf6', '#0891b2', '#ca8a04', '#db2777', '#4f46e5', '#059669', '#9333ea', '#ea580c'];

const formatDate = (iso: string) => {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return format(toZonedTime(d, 'America/Chicago'), 'MMM d, yyyy');
};

// ── Overview: this week, 7-day trend, category mix, offers goal ─────────────

const OFFER_GOAL = 10;

const Overview = () => {
  const { data: trends } = useQuery({ queryKey: ['trends'], queryFn: () => apiClient.getTrends(7) });
  const { data: categoryData } = useQuery({
    queryKey: ['categoryBreakdown'],
    queryFn: () => apiClient.getCategoryBreakdown(new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)),
  });
  const { data: offers } = useQuery({ queryKey: ['offers'], queryFn: () => apiClient.getOffers(100) });

  // Every category the classifier uses, biggest first; the long tail is grouped so the legend stays readable.
  const sorted = [...(categoryData ?? [])].sort((a, b) => b.count - a.count);
  const top = sorted.slice(0, 10);
  const otherCount = sorted.slice(10).reduce((n, d) => n + d.count, 0);
  const pieData: { category: string; count: number }[] = otherCount > 0 ? [...top, { category: 'All smaller categories', count: otherCount }] : top;
  const total = pieData.reduce((n, d) => n + d.count, 0);

  const central = (iso: string) => toZonedTime(new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'), 'America/Chicago');
  const thisMonth = format(toZonedTime(new Date(), 'America/Chicago'), 'yyyy-MM');
  const monthOffers = (offers ?? []).filter((o: any) => o.received_date && format(central(o.received_date), 'yyyy-MM') === thisMonth).length;

  return (
    <div className="space-y-6">
      <WeeklySummary />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 text-center">
            <h2 className="text-base font-bold text-gray-800">Where mail went (last 30 days)</h2>
          </div>
          <div className="p-6">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie data={pieData} dataKey="count" nameKey="category" cx="50%" cy="45%" innerRadius={60} outerRadius={95} paddingAngle={2}>
                    {pieData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => [`${v} (${((v / total) * 100).toFixed(1)}%)`, 'Count']} />
                  <Legend iconType="circle" iconSize={10} formatter={(v) => <span style={{ fontSize: 11 }}>{v}</span>} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="text-sm text-gray-500 text-center py-12">No category data yet</p>}
          </div>
        </div>
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 text-center">
            <h2 className="text-base font-bold text-gray-800">Daily trends (last 7 days)</h2>
          </div>
          <div className="p-6">
            {trends?.trends?.length ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={trends.trends}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" fontSize={11} />
                  <YAxis fontSize={11} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                  <Bar dataKey="total_emails" fill="#3b82f6" name="Total" />
                  <Bar dataKey="interview_requests" fill="#10b981" name="Interviews" />
                  <Bar dataKey="spam_deleted" fill="#ef4444" name="Quarantined" />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="text-sm text-gray-500 text-center py-12">No trend data yet</p>}
          </div>
        </div>
      </div>
      <div className="bg-white shadow rounded-lg p-5">
        <div className="flex justify-between text-sm font-medium text-gray-700 mb-2">
          <span>Offers this month</span><span>{monthOffers} of {OFFER_GOAL}</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div className="bg-green-500 h-2 rounded-full" style={{ width: `${Math.min((monthOffers / OFFER_GOAL) * 100, 100)}%` }} />
        </div>
      </div>
    </div>
  );
};

// ── Weekly Summary ─────────────────────────────────────────────────────────

const WeeklySummary = () => {
  // null = the current week (the server picks Monday to Sunday); the user can pick any range.
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ['weeklySummary', range?.start ?? null, range?.end ?? null],
    queryFn: () => apiClient.getWeeklySummary(range?.start, range?.end),
    placeholderData: (previous) => previous,
  });

  if (isLoading) return <Spinner />;
  if (!data) return <Empty text="No data available" />;

  const stats = [
    { label: 'Emails Processed', value: data.total_emails_processed, color: 'text-blue-600' },
    { label: 'Interview Requests', value: data.interview_requests_found, color: 'text-green-600' },
    { label: 'Emails Organized', value: data.emails_organized, color: 'text-indigo-600' },
    { label: 'Quarantined', value: data.spam_deleted, color: 'text-red-500' },
    { label: 'Processing Runs', value: data.processing_runs, color: 'text-gray-600' },
    { label: 'Successful Runs', value: data.successful_runs, color: 'text-emerald-600' },
    { label: 'Students Notified', value: data.students_notified, color: 'text-purple-600' },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 text-center">
          <h2 className="text-base font-bold text-gray-800">
            {range ? `${data.week_start} — ${data.week_end}` : `Week of ${data.week_start} — ${data.week_end}`}
          </h2>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-3 text-sm text-gray-700">
            <label className="flex items-center gap-1">
              From
              <input
                type="date"
                value={data.week_start}
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) return;
                  setRange({ start: v, end: v > data.week_end ? v : data.week_end });
                }}
                className="rounded-md border-gray-300 text-sm py-1"
                aria-label="Summarise from this date"
              />
            </label>
            <label className="flex items-center gap-1">
              To
              <input
                type="date"
                value={data.week_end}
                min={data.week_start}
                onChange={(e) => { if (e.target.value) setRange({ start: data.week_start, end: e.target.value }); }}
                className="rounded-md border-gray-300 text-sm py-1"
                aria-label="Summarise up to this date"
              />
            </label>
            {range && (
              <button type="button" onClick={() => setRange(null)} className="text-primary-600 hover:underline">
                Reset to this week
              </button>
            )}
          </div>
          {error && <p className="mt-2 text-sm text-red-700" role="alert">{(error as any)?.response?.data?.detail || 'Could not load this range.'}</p>}
        </div>
        <div className="p-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
          {stats.map(s => (
            <div key={s.label} className="bg-gray-50 rounded-lg p-4 text-center">
              <div className={`text-3xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-xs text-gray-500 mt-1 font-medium">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
};

// ── Interview Pipeline ──────────────────────────────────────────────────────

const FUNNEL_COLORS = ['#3b82f6', '#6366f1', '#8b5cf6', '#10b981', '#059669'];

const InterviewPipeline = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['interviewPipeline'],
    queryFn: () => apiClient.getInterviewPipeline(),
  });

  if (isLoading) return <Spinner />;
  if (!data) return <Empty text="No data available" />;

  const stages = [
    { name: 'Total Emails', value: data.total_emails },
    { name: 'Classified as Interview', value: data.classified_as_interview },
    { name: 'Events Created', value: data.events_created },
    { name: 'Students Notified', value: data.students_notified },
    { name: 'Interviews Scheduled', value: data.interviews_scheduled },
  ];

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="bg-gray-200 px-6 py-3 text-center">
        <h2 className="text-base font-bold text-gray-800">Interview Pipeline Funnel</h2>
      </div>
      <div className="p-6">
        <div className="space-y-3 max-w-lg mx-auto">
          {stages.map((stage, idx) => {
            const pct = stages[0].value > 0 ? Math.round((stage.value / stages[0].value) * 100) : 0;
            const width = Math.max(pct, 8);
            return (
              <div key={stage.name}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-medium text-gray-700">{stage.name}</span>
                  <span className="font-bold text-gray-900">{stage.value.toLocaleString()}</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-8 relative overflow-hidden">
                  <div
                    className="h-8 rounded-full flex items-center justify-end pr-3 transition-all"
                    style={{ width: `${width}%`, backgroundColor: FUNNEL_COLORS[idx] }}
                  >
                    <span className="text-white text-xs font-bold">{pct}%</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 text-center mt-4">All-time counts. Percentages are relative to total emails in the database.</p>
      </div>
    </div>
  );
};

// ── Student Activity ────────────────────────────────────────────────────────

const StudentActivity = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['studentActivity'],
    queryFn: () => apiClient.getStudentActivity(),
  });

  if (isLoading) return <Spinner />;
  if (!data || data.length === 0) return <Empty text="No student data yet. Data appears after interview emails are processed." />;

  return (
    <div className="space-y-6">
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 text-center">
          <h2 className="text-base font-bold text-gray-800">Student Activity Report</h2>
        </div>
        <div className="p-4">
          <div className="mb-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" fontSize={11} />
                <YAxis dataKey="student_name" type="category" width={140} fontSize={11} />
                <Tooltip />
                <Bar dataKey="total_interviews" fill="#6366f1" name="Total Interviews" radius={[0, 4, 4, 0]} />
                <Bar dataKey="notified" fill="#10b981" name="Notified" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Student</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Email</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Interviews</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Notified</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Pending</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Last Activity</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((s: any, idx: number) => (
                  <tr key={s.student_id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-3 py-2 font-medium text-gray-900">{s.student_name}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{s.personal_email || '—'}</td>
                    <td className="px-3 py-2 text-center font-bold text-indigo-600">{s.total_interviews}</td>
                    <td className="px-3 py-2 text-center text-green-600 font-semibold">{s.notified}</td>
                    <td className="px-3 py-2 text-center">
                      {s.not_notified > 0
                        ? <span className="text-red-600 font-semibold">{s.not_notified}</span>
                        : <span className="text-gray-400">0</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">
                      {s.last_interview_at ? formatDate(s.last_interview_at) : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${s.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                        {s.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Company Tracker ─────────────────────────────────────────────────────────

const CompanyTracker = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['companyTracker'],
    queryFn: () => apiClient.getCompanyTracker(),
  });

  if (isLoading) return <Spinner />;
  if (!data || data.length === 0) return <Empty text="No company data yet. Appears after interview emails are processed." />;

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="bg-gray-200 px-6 py-3 text-center">
        <h2 className="text-base font-bold text-gray-800">Company / Recruiter Tracker</h2>
      </div>
      <div className="p-6">
        <div className="mb-6">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.slice(0, 15)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" fontSize={11} allowDecimals={false} />
              <YAxis dataKey="company_name" type="category" width={180} fontSize={11} />
              <Tooltip />
              <Bar dataKey="total_requests" fill="#3b82f6" name="Interview Requests" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">#</th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Company</th>
                <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Requests</th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Last Seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((c: any, idx: number) => (
                <tr key={c.company_name} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-3 py-2 text-gray-400 font-medium">{idx + 1}</td>
                  <td className="px-3 py-2 font-medium text-gray-900">{c.company_name}</td>
                  <td className="px-3 py-2 text-center font-bold text-blue-600">{c.total_requests}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{c.last_seen ? formatDate(c.last_seen) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

// ── System: engineering numbers and run history ─────────────────────────────

const System = () => {
  const { data: kpi } = useQuery({ queryKey: ['engineeringKPIs'], queryFn: () => apiClient.getEngineeringKPIs() });
  const { data: runs, isLoading } = useQuery({ queryKey: ['processingRuns', 25], queryFn: () => apiClient.getProcessingRuns(25) });
  const cst = (iso: string) => format(toZonedTime(new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'), 'America/Chicago'), 'MMM d, yyyy h:mm a');
  const failColor = kpi == null ? 'text-gray-400' : kpi.failure_rate_7d === 0 ? 'text-green-600' : kpi.failure_rate_7d < 20 ? 'text-yellow-600' : 'text-red-600';
  const pct = kpi?.db_storage_pct ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white shadow rounded-lg p-5">
          <div className="text-3xl font-bold text-emerald-600">{kpi ? `$${kpi.ai_cost_today_usd.toFixed(4)}` : '—'}</div>
          <div className="text-sm font-bold text-gray-800 mt-1">AI cost today</div>
          <div className="text-xs text-gray-500">GPT spend since midnight UTC</div>
        </div>
        <div className="bg-white shadow rounded-lg p-5">
          <div className="text-3xl font-bold text-blue-600">{kpi?.avg_duration_seconds_7d != null ? `${kpi.avg_duration_seconds_7d}s` : '—'}</div>
          <div className="text-sm font-bold text-gray-800 mt-1">Average run time (7 days)</div>
          <div className="text-xs text-gray-500">{kpi ? `over ${kpi.run_count_7d} run${kpi.run_count_7d !== 1 ? 's' : ''}` : 'rolling average'}</div>
        </div>
        <div className="bg-white shadow rounded-lg p-5">
          <div className={`text-3xl font-bold ${failColor}`}>{kpi ? `${kpi.failure_rate_7d}%` : '—'}</div>
          <div className="text-sm font-bold text-gray-800 mt-1">Failure rate (7 days)</div>
          <div className="text-xs text-gray-500">{kpi ? `${kpi.failed_run_count_7d} of ${kpi.run_count_7d} runs failed` : 'last 7 days'}</div>
        </div>
        {kpi?.db_storage_used_bytes != null && (
          <div className="bg-white shadow rounded-lg p-5">
            <div className="text-sm font-bold text-gray-800">Database storage</div>
            <div className="text-xs text-gray-500 mt-1">{formatStorage(kpi.db_storage_used_bytes)} / {formatStorage(kpi.db_storage_cap_bytes)} ({pct}%)</div>
            <div className="mt-3 h-1.5 w-full rounded-full bg-gray-200 overflow-hidden">
              <div className={`h-full rounded-full ${pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-yellow-500' : 'bg-green-500'}`} style={{ width: `${Math.min(pct, 100)}%` }} />
            </div>
          </div>
        )}
      </div>
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3 text-center">
          <h2 className="text-base font-bold text-gray-800">Processing runs (last 25)</h2>
        </div>
        <div className="p-4 overflow-x-auto">
          {isLoading ? <Spinner /> : runs && runs.length > 0 ? (
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Date / time (Central)</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Emails</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Interviews</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Organized</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Quarantined</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {runs.map((r, i) => (
                  <tr key={r.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-3 py-2 whitespace-nowrap font-medium text-gray-900">{cst(r.run_timestamp)}</td>
                    <td className="px-3 py-2 text-right text-gray-700">{r.total_emails}</td>
                    <td className="px-3 py-2 text-right font-semibold text-green-600">{r.interview_requests}</td>
                    <td className="px-3 py-2 text-right text-gray-700">{r.organized}</td>
                    <td className="px-3 py-2 text-right text-red-600">{r.spam_deleted}</td>
                    <td className="px-3 py-2 text-center">
                      <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${r.status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>{r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-sm text-gray-500 text-center py-8">No processing runs yet</p>}
        </div>
      </div>
    </div>
  );
};

// ── Helpers ─────────────────────────────────────────────────────────────────

const Spinner = () => (
  <div className="flex justify-center py-16">
    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary-600" />
  </div>
);

const Empty = ({ text }: { text: string }) => (
  <div className="bg-white shadow rounded-lg p-12 text-center text-gray-500">{text}</div>
);

// ── Main Page ────────────────────────────────────────────────────────────────

const ReportsPage = () => {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') || 'overview';
  const activeTab = TABS.some(t => t.id === requested) ? requested : 'overview';
  const setActiveTab = (id: string) => setParams(id === 'overview' ? {} : { tab: id }, { replace: true });

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-1 text-sm text-gray-600">Looking back: how the week went, every interview, and how the system is running. What needs you today is on the Dashboard.</p>
      </div>

      {/* Tab bar */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="flex overflow-x-auto">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 min-w-max px-5 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-700 bg-primary-50'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && <Overview />}
      {activeTab === 'interviews' && <InterviewsPage embedded />}
      {activeTab === 'pipeline' && <InterviewPipeline />}
      {activeTab === 'students' && <StudentActivity />}
      {activeTab === 'companies' && <CompanyTracker />}
      {activeTab === 'system' && <System />}
    </div>
  );
};

export default ReportsPage;
