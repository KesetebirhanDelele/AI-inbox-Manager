import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { format } from 'date-fns';
import type { Approval } from '../types';
import EmailBodyPanel from './EmailBodyPanel';

const ApprovalsContent = () => {
  const queryClient = useQueryClient();
  const [selectedApproval, setSelectedApproval] = useState<Approval | null>(null);
  const [action, setAction] = useState<'keep_inbox' | 'move_to_folder' | 'delete'>('keep_inbox');
  const [targetFolder, setTargetFolder] = useState('Job Alerts');
  const [notes, setNotes] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');

  const { data: approvals, isLoading } = useQuery({
    queryKey: ['pendingApprovals'],
    queryFn: () => apiClient.getPendingApprovals(),
  });

  const approveMutation = useMutation({
    mutationFn: (params: { id: number; action: string; targetFolder?: string; notes?: string }) =>
      apiClient.approveEmail(params.id, params.action, params.targetFolder, params.notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pendingApprovals'] });
      queryClient.invalidateQueries({ queryKey: ['summaryStats'] });
      setSelectedApproval(null);
      setNotes('');
    },
  });

  const handleApprove = () => {
    if (!selectedApproval) return;
    approveMutation.mutate({
      id: selectedApproval.id,
      action,
      targetFolder: action === 'move_to_folder' ? targetFolder : undefined,
      notes: notes || undefined,
    });
  };

  // Unique categories for filter dropdown
  const categories = useMemo(() => {
    if (!approvals) return [];
    return Array.from(new Set(approvals.map((a) => a.category))).sort();
  }, [approvals]);

  const filteredApprovals = useMemo(() => {
    if (!approvals) return [];
    const q = searchQuery.toLowerCase();
    return approvals.filter((approval) => {
      const matchesSearch =
        !q ||
        (approval.email_subject || '').toLowerCase().includes(q) ||
        (approval.email_from || '').toLowerCase().includes(q) ||
        (approval.company_name || '').toLowerCase().includes(q);
      const matchesCategory = !categoryFilter || approval.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [approvals, searchQuery, categoryFilter]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (!approvals || approvals.length === 0) {
    return (
      <div className="text-center py-12">
        <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 className="mt-2 text-sm font-medium text-gray-900">No pending approvals</h3>
        <p className="mt-1 text-sm text-gray-500">
          All emails have been reviewed or have high confidence classifications.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search + Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400"
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search subject, sender, company…"
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setSelectedApproval(null); }}
            className="pl-9 pr-3 py-1.5 w-full text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        <select
          value={categoryFilter}
          onChange={(e) => { setCategoryFilter(e.target.value); setSelectedApproval(null); }}
          className="py-1.5 pl-3 pr-8 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
        >
          <option value="">All Categories</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
        </select>
      </div>

      {/* Results count */}
      <p className="text-sm text-gray-500">
        {filteredApprovals.length} of {approvals.length} approval{approvals.length !== 1 ? 's' : ''}
        {(searchQuery || categoryFilter) && (
          <button
            onClick={() => { setSearchQuery(''); setCategoryFilter(''); setSelectedApproval(null); }}
            className="ml-2 text-primary-600 hover:underline"
          >
            Clear filters
          </button>
        )}
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Approval List */}
        <div className="space-y-4">
          {filteredApprovals.length === 0 ? (
            <div className="text-center py-10 bg-white rounded-lg shadow">
              <p className="text-sm text-gray-500">No approvals match your search.</p>
            </div>
          ) : (
            filteredApprovals.map((approval) => (
              <div
                key={approval.id}
                className={`bg-white shadow rounded-lg p-4 cursor-pointer transition-colors ${
                  selectedApproval?.id === approval.id
                    ? 'ring-2 ring-primary-500'
                    : 'hover:bg-gray-50'
                }`}
                onClick={() => setSelectedApproval(approval)}
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {approval.email_subject}
                    </p>
                    <p className="text-xs text-gray-500 mt-1 truncate">
                      From: {approval.email_from}
                    </p>
                    <p className="text-xs text-gray-500">
                      {format(new Date(approval.email_received_date), 'MMM d, yyyy h:mm a')}
                    </p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                    {approval.category}
                  </span>
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      approval.confidence >= 0.7
                        ? 'bg-green-100 text-green-800'
                        : 'bg-orange-100 text-orange-800'
                    }`}
                  >
                    {(approval.confidence * 100).toFixed(0)}% confident
                  </span>
                  {approval.company_name && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                      {approval.company_name}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Approval Actions */}
        {selectedApproval && (
          <div className="bg-white shadow rounded-lg p-6 sticky top-6 max-h-[calc(100vh-3rem)] overflow-y-auto">
            <h3 className="text-lg font-medium text-gray-900 mb-1">Review Email</h3>
            <p className="text-sm text-gray-500 mb-4 truncate">{selectedApproval.email_subject}</p>

            {/* The email itself, so a decision never needs a trip back to Gmail */}
            <div className="mb-5">
              <EmailBodyPanel key={selectedApproval.email_id} emailId={selectedApproval.email_id} />
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Action</label>
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value as any)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                >
                  <option value="keep_inbox">Keep in Inbox</option>
                  <option value="move_to_folder">Move to Folder</option>
                  <option value="delete">Delete</option>
                </select>
              </div>

              {action === 'move_to_folder' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Target Folder</label>
                  <select
                    value={targetFolder}
                    onChange={(e) => setTargetFolder(e.target.value)}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                  >
                    <option>Job Alerts</option>
                    <option>Interview Confirmation</option>
                    <option>Interview Scheduling</option>
                    <option>Rejection</option>
                    <option>More Information Request</option>
                  </select>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Notes (optional)</label>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                  placeholder="Add any notes about this decision..."
                />
              </div>

              <div className="pt-4 space-y-3">
                <button
                  onClick={handleApprove}
                  disabled={approveMutation.isPending}
                  className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
                >
                  {approveMutation.isPending ? 'Processing...' : 'Approve'}
                </button>
                <button
                  onClick={() => setSelectedApproval(null)}
                  className="w-full flex justify-center py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ApprovalsContent;
