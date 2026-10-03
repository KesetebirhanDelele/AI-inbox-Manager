import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/**
 * Who holds each role (approver, callback owner, escalation) and the pilot limit.
 * Roles are assigned here, never written into the code, so moving the work to recruiters is a settings change.
 */
const RolesCard = () => {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['roles'], queryFn: () => apiClient.getRoles() });
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [pilot, setPilot] = useState('');

  useEffect(() => {
    if (!data) return;
    setEmails(Object.fromEntries(data.roles.map((r) => [r.role, r.email])));
    setPilot(String(data.pilot_limit));
  }, [data]);

  const save = useMutation({
    mutationFn: (role: string) => apiClient.assignRole(role, emails[role] || ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['roles'] }),
  });
  const savePilot = useMutation({
    mutationFn: () => apiClient.setPilotLimit(Number(pilot)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['roles'] }),
  });
  const errorOf = (e: unknown) => (e as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;

  if (isLoading || !data) {
    return <div className="bg-white shadow rounded-lg p-6 text-sm text-gray-500">Loading roles...</div>;
  }

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-5 sm:p-6 space-y-5">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Roles and alerts</h2>
          <p className="mt-1 text-sm text-gray-600">
            Who gets each alert is assigned here, not written into the system. When the work moves to recruiters, change the
            email next to the role.
          </p>
        </div>

        {data.roles.map((r) => (
          <div key={r.role} className="border border-gray-200 rounded-md p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium text-gray-900">{r.label}</div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${r.email ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                {r.email ? `Assigned (${r.source})` : 'Nobody assigned: alerts are only logged'}
              </span>
            </div>
            <div className="text-xs text-gray-500">{r.help}</div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="email"
                value={emails[r.role] ?? ''}
                onChange={(e) => setEmails({ ...emails, [r.role]: e.target.value })}
                placeholder="email address"
                className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-md"
              />
              <button
                type="button"
                disabled={save.isPending}
                onClick={() => save.mutate(r.role)}
                className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
        ))}
        {save.isError && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-800">{errorOf(save.error) || 'Could not save.'}</div>}

        <div className="border border-gray-200 rounded-md p-3 space-y-2">
          <div className="font-medium text-gray-900">Pilot limit</div>
          <div className="text-xs text-gray-500">
            Until you lift it, only this many approved notices may start a call, text and email sequence ({data.pilot_used} started so far).
            Set 0 for no limit once the pilot has run clean.
          </div>
          <div className="flex gap-2">
            <input type="number" min={0} value={pilot} onChange={(e) => setPilot(e.target.value)}
              className="w-28 px-3 py-2 text-sm border border-gray-300 rounded-md" />
            <button type="button" disabled={savePilot.isPending} onClick={() => savePilot.mutate()}
              className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
              Save
            </button>
          </div>
          {savePilot.isError && <div className="text-sm text-red-800">{errorOf(savePilot.error) || 'Could not save.'}</div>}
        </div>

        <div className="text-xs text-gray-500">
          Business hours used for "within one business hour" and "waiting more than 2 business hours": {data.business_hours}.
        </div>
      </div>
    </div>
  );
};

export default RolesCard;
