import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { format } from 'date-fns';

const SettingsPage = () => {
  const queryClient = useQueryClient();
  const [newCompany, setNewCompany] = useState('');
  const [notes, setNotes] = useState('');

  const { data: whitelist, isLoading } = useQuery({
    queryKey: ['whitelist'],
    queryFn: () => apiClient.getWhitelist(),
  });

  const addMutation = useMutation({
    mutationFn: (params: { companyName: string; notes?: string }) =>
      apiClient.addToWhitelist(params.companyName, params.notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['whitelist'] });
      setNewCompany('');
      setNotes('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (companyId: number) => apiClient.removeFromWhitelist(companyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['whitelist'] });
    },
  });

  const { data: scheduleConfig, isLoading: scheduleLoading } = useQuery({
    queryKey: ['scheduleConfig'],
    queryFn: () => apiClient.getScheduleConfig(),
  });

  const handleAdd = () => {
    if (newCompany.trim()) {
      addMutation.mutate({
        companyName: newCompany.trim(),
        notes: notes.trim() || undefined,
      });
    }
  };

  const handleRemove = (companyId: number) => {
    if (window.confirm('Are you sure you want to remove this company from the whitelist?')) {
      removeMutation.mutate(companyId);
    }
  };

  const getIntervalLabel = (minutes: number): string => {
    if (minutes % 60 === 0) {
      const hours = minutes / 60;
      return hours === 1 ? 'Every hour' : `Every ${hours} hours`;
    }
    return `Every ${minutes} minutes`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="mt-1 text-sm text-gray-600">
          View the processing schedule and manage the whitelist
        </p>
      </div>

      {/* Processing Schedule Configuration */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">
            Processing Schedule
          </h2>
          <p className="text-sm text-gray-600 mb-4">
            How often emails are processed and how many are handled each run.
            These are set on the server and can't be changed from this page.
          </p>

          {scheduleLoading ? (
            <div className="flex justify-center py-4">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
            </div>
          ) : (
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 max-w-xl">
              <div>
                <dt className="text-sm font-medium text-gray-700">Processing interval</dt>
                <dd className="mt-1 text-sm font-medium text-gray-900">
                  {scheduleConfig ? getIntervalLabel(scheduleConfig.interval_minutes) : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-700">Emails per run</dt>
                <dd className="mt-1 text-sm font-medium text-gray-900">
                  {scheduleConfig ? `Up to ${scheduleConfig.batch_size}` : '—'}
                </dd>
              </div>
            </dl>
          )}
        </div>
      </div>

      {/* Whitelist Management */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">
            Whitelist Management
          </h2>
          <p className="text-sm text-gray-600 mb-4">
            Companies on the whitelist are never moved or deleted, regardless of AI classification.
          </p>

          {/* Add Company Form */}
          <div className="border border-gray-300 rounded-lg p-4 mb-6">
            <h3 className="text-sm font-medium text-gray-900 mb-3">
              Add Company to Whitelist
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Company Name
                </label>
                <input
                  type="text"
                  value={newCompany}
                  onChange={(e) => setNewCompany(e.target.value)}
                  placeholder="e.g., Acme Corporation"
                  className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Notes (optional)
                </label>
                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Reason for adding to whitelist"
                  className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                />
              </div>
              <button
                onClick={handleAdd}
                disabled={!newCompany.trim() || addMutation.isPending}
                className="w-full sm:w-auto px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {addMutation.isPending ? 'Adding...' : 'Add to Whitelist'}
              </button>
            </div>
          </div>

          {/* Whitelist Table */}
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            </div>
          ) : !whitelist || whitelist.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">
              No companies in whitelist
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-300">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">
                      Company Name
                    </th>
                    <th className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">
                      Added By
                    </th>
                    <th className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">
                      Date Added
                    </th>
                    <th className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">
                      Notes
                    </th>
                    <th className="relative py-3.5 pl-3 pr-4 sm:pr-6">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {whitelist.map((company) => (
                    <tr key={company.id}>
                      <td className="whitespace-nowrap px-3 py-4 text-sm font-medium text-gray-900">
                        {company.company_name}
                      </td>
                      <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500">
                        {company.added_by}
                      </td>
                      <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500">
                        {format(new Date(company.added_date), 'MMM d, yyyy')}
                      </td>
                      <td className="px-3 py-4 text-sm text-gray-500 max-w-xs truncate">
                        {company.notes || '-'}
                      </td>
                      <td className="relative whitespace-nowrap py-4 pl-3 pr-4 text-right text-sm font-medium sm:pr-6">
                        <button
                          onClick={() => handleRemove(company.id)}
                          disabled={removeMutation.isPending}
                          className="text-red-600 hover:text-red-900 disabled:opacity-50"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
