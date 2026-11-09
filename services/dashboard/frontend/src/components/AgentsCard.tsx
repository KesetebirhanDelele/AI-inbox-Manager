import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/**
 * The email for each student's agent (names come from the roster sheet's Agent column). A new notification card goes to the student's
 * agent first; the approver is told if the agent has not decided in time, or straight away when a card needs a person to sort it out.
 */
const AgentsCard = () => {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['agents'], queryFn: () => apiClient.getAgents() });
  const [emails, setEmails] = useState<Record<string, string>>({});
  useEffect(() => {
    if (data) setEmails(Object.fromEntries(data.agents.map((a) => [a.agent, a.email])));
  }, [data]);
  const save = useMutation({
    mutationFn: (agent: string) => apiClient.setAgentEmail(agent, emails[agent] || ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  });
  const remove = useMutation({
    mutationFn: (agent: string) => apiClient.setAgentEmail(agent, ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  });
  const [newName, setNewName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const add = useMutation({
    mutationFn: () => apiClient.setAgentEmail(newName, newEmail),
    onSuccess: () => { setNewName(''); setNewEmail(''); queryClient.invalidateQueries({ queryKey: ['agents'] }); },
  });
  const errorOf =(e: unknown) => (e as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;

  if (!data) return null;

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-5 sm:p-6 space-y-4">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Agents</h2>
          <p className="mt-1 text-sm text-gray-600">
            A new notification card goes to the student&apos;s agent first (from the roster sheet). If the agent has not decided within the backup
            time, the approver is told. A card that needs a person first (student not on the roster or not in GHL, unverified, or an uncertain
            email classification) goes straight to the approver. An agent with no email here is skipped, so the approver gets their cards.
            Remove clears an agent's email; an agent named on the roster sheet stays listed with no email (take the name off the sheet to drop them completely). Leave every email empty to keep everything with the approver.
          </p>
        </div>
        {!data.roster_readable && (
          <p className="text-sm text-amber-700">The roster sheet could not be read right now, so agent names may be missing. Cards go to the approver meanwhile.</p>
        )}
        <ul className="divide-y divide-gray-100 text-sm">
          {data.agents.map((a) => (
            <li key={a.agent} className="py-2 flex flex-wrap items-center gap-3">
              <span className="font-medium text-gray-900 w-40">{a.agent}</span>
              <span className="text-xs text-gray-500 w-24">{a.students} active student{a.students === 1 ? '' : 's'}</span>
              <input
                type="email"
                placeholder="agent@company.com"
                value={emails[a.agent] ?? ''}
                onChange={(e) => setEmails({ ...emails, [a.agent]: e.target.value })}
                className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-72"
              />
              <button
                onClick={() => save.mutate(a.agent)}
                disabled={save.isPending || (emails[a.agent] ?? '') === a.email}
                className="px-3 py-1.5 text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50"
              >
                Save
              </button>
              {a.email && (
                <button
                  onClick={() => { if (window.confirm(`Remove ${a.agent}? Their students' cards will go to the approver.`)) remove.mutate(a.agent); }}
                  disabled={remove.isPending}
                  className="ml-auto text-xs font-medium text-red-600 hover:text-red-700"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
          {data.agents.length === 0 && <li className="py-2 text-gray-500">No agents found on the roster sheet.</li>}
        </ul>
        <form
          className="flex flex-wrap items-end gap-3 pt-2"
          onSubmit={(e) => { e.preventDefault(); add.mutate(); }}
        >
          <input required placeholder="agent name (as on the roster sheet)" value={newName} onChange={(e) => setNewName(e.target.value)}
                 className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-64" />
          <input required type="email" placeholder="agent@company.com" value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
                 className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-72" />
          <button type="submit" disabled={add.isPending} className="px-3 py-1.5 text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50">
            Add agent
          </button>
        </form>
        {(save.isError || add.isError || remove.isError) && <p className="text-sm text-red-700">{errorOf(save.error) || errorOf(add.error) || errorOf(remove.error) || 'That did not work.'}</p>}
      </div>
    </div>
  );
};

export default AgentsCard;
