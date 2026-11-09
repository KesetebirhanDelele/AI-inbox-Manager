import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/** Who may sign in by emailed link. Shown only to people who manage access. */
const UsersCard = () => {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['allowed-users'], queryFn: () => apiClient.getAllowedUsers() });
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState('admin');
  const [canManage, setCanManage] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['allowed-users'] });
  const errorOf = (e: unknown) => (e as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;

  const add = useMutation({
    mutationFn: () => apiClient.addAllowedUser({ email, name: name || undefined, role, can_manage: canManage }),
    onSuccess: () => { setEmail(''); setName(''); setCanManage(false); refresh(); },
  });
  const change = useMutation({
    mutationFn: (v: { id: number; active?: boolean; can_manage?: boolean }) => apiClient.changeAllowedUser(v.id, v),
    onSuccess: refresh,
  });

  if (!data || !data.can_manage) return null;

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-5 sm:p-6 space-y-4">
        <div>
          <h2 className="text-lg font-medium text-gray-900">People who can sign in</h2>
          <p className="mt-1 text-sm text-gray-600">
            Each person signs in with their email: the app emails them a one-time link, no password. Removing someone signs them out and stops new links.
          </p>
        </div>
        <ul className="divide-y divide-gray-100 text-sm">
          {data.users.map((u) => (
            <li key={u.id} className="py-2 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className={`font-medium ${u.active ? 'text-gray-900' : 'text-gray-400 line-through'}`}>{u.email}</span>
              {u.name && <span className="text-gray-500">{u.name}</span>}
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{u.role}</span>
              {u.can_manage && <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">manages access</span>}
              <span className="text-xs text-gray-400">{u.last_login_at ? `last sign-in ${new Date(u.last_login_at + 'Z').toLocaleString()}` : 'never signed in'}</span>
              <button
                className="ml-auto text-xs font-medium text-red-600 hover:text-red-700"
                onClick={() => change.mutate({ id: u.id, active: !u.active })}
              >
                {u.active ? 'Remove' : 'Restore'}
              </button>
            </li>
          ))}
          {data.users.length === 0 && <li className="py-2 text-gray-500">Nobody yet.</li>}
        </ul>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => { e.preventDefault(); add.mutate(); }}
        >
          <input type="email" required placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-64" />
          <input placeholder="name (optional)" value={name} onChange={(e) => setName(e.target.value)}
                 className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-44" />
          <select value={role} onChange={(e) => setRole(e.target.value)} className="border border-gray-300 rounded-md px-2 py-1.5 text-sm">
            <option value="admin">admin (full)</option>
            <option value="stakeholder">stakeholder (view only)</option>
          </select>
          <label className="text-sm text-gray-700 flex items-center gap-1">
            <input type="checkbox" checked={canManage} onChange={(e) => setCanManage(e.target.checked)} /> can manage this list
          </label>
          <button type="submit" disabled={add.isPending} className="px-3 py-1.5 text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50">
            Add person
          </button>
        </form>
        {(add.isError || change.isError) && <p className="text-sm text-red-700">{errorOf(add.error) || errorOf(change.error) || 'That did not work.'}</p>}
      </div>
    </div>
  );
};

export default UsersCard;
