import { useState, Fragment, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import InterviewChecklist from '../components/InterviewChecklist';
import type { InterviewRequest, UpcomingInterview } from '../types';

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

const PAGE_SIZE = 25;

const InterviewsPage = () => {
  const [expandedInterviewId, setExpandedInterviewId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(0);

  const { data: interviews, isLoading } = useQuery({
    queryKey: ['interviews'],
    queryFn: () => apiClient.getInterviewRequests(200, 0),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const { data: countData } = useQuery({
    queryKey: ['interviewCount'],
    queryFn: () => apiClient.getInterviewCount(),
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

  const toggleExpand = (interviewId: number) => {
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

  const filteredInterviews = useMemo(() => {
    if (!interviews) return [];
    const q = searchQuery.toLowerCase();
    return interviews.filter((interview: InterviewRequest) => {
      const matchesSearch =
        !q ||
        (interview.student_name || '').toLowerCase().includes(q) ||
        (interview.company_name || '').toLowerCase().includes(q) ||
        (interview.position || '').toLowerCase().includes(q) ||
        (interview.subject || '').toLowerCase().includes(q);
      const matchesType = !typeFilter || interview.interview_type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [interviews, searchQuery, typeFilter]);

  const totalPages = Math.ceil(filteredInterviews.length / PAGE_SIZE);
  const paginatedInterviews = filteredInterviews.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE
  );

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    setCurrentPage(0);
    setExpandedInterviewId(null);
  };

  const handleTypeFilterChange = (value: string) => {
    setTypeFilter(value);
    setCurrentPage(0);
    setExpandedInterviewId(null);
  };

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
        <h1 className="text-2xl font-bold text-gray-900">Interview Requests</h1>
        <p className="mt-1 text-sm text-gray-600">
          All detected interview requests from your processed emails. Click a row to see the process checklist.
        </p>
      </div>

      {/* Summary Card */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-500">Total Interview Requests</p>
            <p className="mt-1 text-3xl font-bold text-green-600">{countData?.count || 0}</p>
          </div>
          <div className="p-3 bg-green-100 rounded-full">
            <svg className="h-8 w-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
        </div>
      </div>

      {/* Interview Requests List */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <h2 className="text-lg font-medium text-gray-900">Recent Interview Requests</h2>
            <div className="flex flex-col sm:flex-row gap-2">
              {/* Search */}
              <div className="relative">
                <svg
                  className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400"
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                </svg>
                <input
                  type="text"
                  placeholder="Search student, company, position…"
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  className="pl-9 pr-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 w-64"
                />
              </div>
              {/* Type filter */}
              <select
                value={typeFilter}
                onChange={(e) => handleTypeFilterChange(e.target.value)}
                className="py-1.5 pl-3 pr-8 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
              >
                <option value="">All Types</option>
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Results count */}
          {(searchQuery || typeFilter) && (
            <p className="text-sm text-gray-500 mb-3">
              {filteredInterviews.length} result{filteredInterviews.length !== 1 ? 's' : ''}
              {searchQuery && ` for "${searchQuery}"`}
              {typeFilter && ` · ${TYPE_LABELS[typeFilter] || typeFilter}`}
            </p>
          )}

          {paginatedInterviews.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-8"></th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Student</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Position</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Subject</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Received</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Confidence</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {paginatedInterviews.map((interview: InterviewRequest) => {
                      const isExpanded = expandedInterviewId === interview.id;
                      return (
                        <Fragment key={interview.id}>
                          <tr
                            className={`cursor-pointer transition-colors ${
                              isExpanded ? 'bg-blue-50' : 'hover:bg-gray-50'
                            }`}
                            onClick={() => toggleExpand(interview.id)}
                          >
                            <td className="px-3 py-4 whitespace-nowrap">
                              <svg
                                className={`h-5 w-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                fill="none" viewBox="0 0 24 24" stroke="currentColor"
                              >
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                              </svg>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                              {interview.student_name || 'Unknown'}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <span className={`px-2 py-1 text-xs font-medium rounded ${getTypeStyle(interview.interview_type)}`}>
                                {getTypeLabel(interview.interview_type)}
                              </span>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {interview.company_name || '-'}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {interview.position || '-'}
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-900 max-w-xs truncate">
                              {interview.subject}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {formatDateCST(interview.received_date)}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <span className={`px-2 py-1 text-xs font-medium rounded ${
                                interview.confidence >= 0.90
                                  ? 'bg-green-100 text-green-800'
                                  : interview.confidence >= 0.80
                                  ? 'bg-yellow-100 text-yellow-800'
                                  : 'bg-orange-100 text-orange-800'
                              }`}>
                                {(interview.confidence * 100).toFixed(0)}%
                              </span>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr>
                              <td colSpan={8} className="p-0">
                                <div onClick={(e) => e.stopPropagation()}>
                                  {interview.interview_event_id ? (
                                    <InterviewChecklist interviewEventId={interview.interview_event_id} />
                                  ) : (
                                    <div className="border-t border-gray-200 bg-gray-50 px-6 py-4 text-sm text-gray-500">
                                      No checklist available. This interview has not been sub-classified yet.
                                    </div>
                                  )}
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

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between border-t border-gray-200 pt-4">
                  <p className="text-sm text-gray-500">
                    Showing {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filteredInterviews.length)} of {filteredInterviews.length}
                  </p>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                      disabled={currentPage === 0}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Previous
                    </button>
                    <div className="flex items-center space-x-1">
                      {Array.from({ length: totalPages }, (_, i) => i).map((page) => (
                        <button
                          key={page}
                          onClick={() => setCurrentPage(page)}
                          className={`px-3 py-1.5 text-sm rounded-md ${
                            page === currentPage
                              ? 'bg-primary-600 text-white'
                              : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {page + 1}
                        </button>
                      ))}
                    </div>
                    <button
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
              {searchQuery || typeFilter ? (
                <>
                  <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                  </svg>
                  <h3 className="mt-2 text-sm font-medium text-gray-900">No results found</h3>
                  <p className="mt-1 text-sm text-gray-500">Try adjusting your search or filter.</p>
                  <button
                    onClick={() => { handleSearchChange(''); handleTypeFilterChange(''); }}
                    className="mt-3 text-sm text-primary-600 hover:underline"
                  >
                    Clear filters
                  </button>
                </>
              ) : (
                <>
                  <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                  </svg>
                  <h3 className="mt-2 text-sm font-medium text-gray-900">No interview requests</h3>
                  <p className="mt-1 text-sm text-gray-500">No interview requests have been detected yet.</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Upcoming Scheduled Interviews */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="bg-gray-200 px-6 py-3">
          <h2 className="text-base font-bold text-gray-800 text-center">Upcoming Scheduled Interviews</h2>
        </div>
        <div className="px-4 py-5 sm:p-6">
          {upcomingInterviews && upcomingInterviews.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Date</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Time</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Candidate</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Company</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Position</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Type</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Format</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Link</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(upcomingInterviews as UpcomingInterview[]).map((item, idx) => {
                    const isToday = item.interview_date === new Date().toISOString().slice(0, 10);
                    return (
                      <tr key={item.interview_event_id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-3 py-2 whitespace-nowrap font-medium text-gray-900">
                          <span className={isToday ? 'text-primary-600 font-bold' : ''}>
                            {item.interview_date
                              ? new Date(item.interview_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                              : '—'}
                          </span>
                          {isToday && (
                            <span className="ml-2 px-1.5 py-0.5 text-xs bg-primary-100 text-primary-700 rounded font-semibold">Today</span>
                          )}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                          {item.interview_time || '—'}
                          {item.interview_timezone && (
                            <span className="ml-1 text-xs text-gray-400">{item.interview_timezone}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-900 font-medium">{item.student_name || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-700">{item.company_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-700 max-w-[160px] truncate" title={item.position || ''}>{item.position || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {item.interview_type ? (
                            <span className={`px-2 py-0.5 text-xs font-medium rounded ${TYPE_STYLES[item.interview_type] || 'bg-gray-100 text-gray-800'}`}>
                              {TYPE_LABELS[item.interview_type] || item.interview_type}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-700 capitalize">{item.interview_format || '—'}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {item.meeting_link ? (
                            <a
                              href={item.meeting_link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center text-primary-600 hover:text-primary-800 text-xs font-medium"
                            >
                              Join
                              <svg className="ml-1 h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                              </svg>
                            </a>
                          ) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">No interviews with a confirmed date yet. Requests that do not state a date stay in the list above until a date is known.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default InterviewsPage;
