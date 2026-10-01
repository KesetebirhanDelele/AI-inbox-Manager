import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { apiClient } from '../api/client';

const TABS = [
  { id: 'weekly', label: 'Weekly Summary' },
  { id: 'pipeline', label: 'Interview Pipeline' },
  { id: 'students', label: 'Student Activity' },
  { id: 'companies', label: 'Company Tracker' },
  { id: 'missed', label: 'Missed Interviews' },
];

const formatCST = (iso: string) => {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return format(toZonedTime(d, 'America/Chicago'), 'MMM d, yyyy h:mm a');
};

const formatDate = (iso: string) => {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return format(toZonedTime(d, 'America/Chicago'), 'MMM d, yyyy');
};

// ── Weekly Summary ─────────────────────────────────────────────────────────

const WeeklySummary = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['weeklySummary'],
    queryFn: () => apiClient.getWeeklySummary(),
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
            Week of {data.week_start} — {data.week_end}
          </h2>
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

      {data.top_companies.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="bg-gray-200 px-6 py-3 text-center">
            <h2 className="text-base font-bold text-gray-800">Top Companies This Week</h2>
          </div>
          <div className="p-6">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.top_companies} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" fontSize={11} />
                <YAxis dataKey="company" type="category" width={160} fontSize={11} />
                <Tooltip />
                <Bar dataKey="count" fill="#6366f1" name="Requests" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
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
        <p className="text-xs text-gray-400 text-center mt-4">Percentages relative to total emails in database</p>
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

// ── Missed Interviews ───────────────────────────────────────────────────────

const MissedInterviews = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['missedInterviews'],
    queryFn: () => apiClient.getMissedInterviews(),
  });

  if (isLoading) return <Spinner />;
  if (!data || data.length === 0) return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="bg-gray-200 px-6 py-3 text-center">
        <h2 className="text-base font-bold text-gray-800">Missed Interviews Alert</h2>
      </div>
      <div className="p-12 text-center">
        <div className="text-green-500 text-5xl mb-3">✓</div>
        <p className="text-gray-600 font-medium">All interview requests have been handled!</p>
        <p className="text-gray-400 text-sm mt-1">No students are missing notifications.</p>
      </div>
    </div>
  );

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="bg-gray-200 px-6 py-3 flex items-center justify-center gap-3">
        <h2 className="text-base font-bold text-gray-800">Missed Interviews Alert</h2>
        <span className="bg-red-100 text-red-700 text-xs font-bold px-2 py-0.5 rounded-full">{data.length} unhandled</span>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead>
            <tr className="bg-gray-50">
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Received</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Company</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Position</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Student</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Notification</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.map((item: any, idx: number) => (
              <tr key={item.email_id} className={idx % 2 === 0 ? 'bg-white' : 'bg-red-50'}>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700 text-xs">{formatCST(item.received_date)}</td>
                <td className="px-3 py-2 font-medium text-gray-900">{item.company_name || '—'}</td>
                <td className="px-3 py-2 text-gray-600 max-w-[160px] truncate">{item.position || '—'}</td>
                <td className="px-3 py-2 text-gray-700">{item.student_name || '—'}</td>
                <td className="px-3 py-2 text-center">
                  <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-red-100 text-red-700">
                    {item.notification_status === 'not_created' ? 'Not Created' : item.notification_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
  const [activeTab, setActiveTab] = useState('weekly');

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-1 text-sm text-gray-600">Analytics and insights across all email processing activity</p>
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
      {activeTab === 'weekly' && <WeeklySummary />}
      {activeTab === 'pipeline' && <InterviewPipeline />}
      {activeTab === 'students' && <StudentActivity />}
      {activeTab === 'companies' && <CompanyTracker />}
      {activeTab === 'missed' && <MissedInterviews />}
    </div>
  );
};

export default ReportsPage;
