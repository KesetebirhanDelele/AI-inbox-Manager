import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import type { GateReviewItem } from '../types';

const SAYS: Record<string, { label: string; cls: string }> = {
  real: { label: 'Gate: real interview news (a card shows)', cls: 'bg-green-100 text-green-800' },
  not_real: { label: 'Gate: no news (would hide the card)', cls: 'bg-red-100 text-red-800' },
  unsure: { label: 'Gate: not sure (card shows as today)', cls: 'bg-yellow-100 text-yellow-800' },
};

const SHOW = [
  { id: 'undecided', label: 'To decide' },
  { id: 'disagree', label: 'Gate and I disagree' },
  { id: 'decided', label: 'Decided' },
  { id: 'all', label: 'All' },
];

const when = (iso: string) =>
  new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString('en-US', { timeZone: 'America/Chicago' }) + ' CT';

function Row({ item }: { item: GateReviewItem }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const decide = useMutation({
    mutationFn: (d: 'real' | 'not_real' | 'clear') => apiClient.decideGateReview(item.id, d, note || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gateReviews'] });
      queryClient.invalidateQueries({ queryKey: ['gateSummary'] });
    },
  });
  const says = SAYS[item.gate_says];
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${says.cls}`}>{says.label}</span>
        {item.flag && <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">{item.flag}</span>}
        {item.notice_status && <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">Notice today: {item.notice_status}</span>}
        {item.source === 'replay' && <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">Past email</span>}
        {item.human_decision && (
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-white">
            You said: {item.human_decision === 'real' ? 'real' : 'not real'}
          </span>
        )}
      </div>
      <div>
        <div className="font-medium text-gray-900">{item.subject}</div>
        <div className="text-xs text-gray-500">{item.from_address} · {when(item.received_date)}</div>
      </div>
      <div className="text-sm text-gray-800">
        <span className="font-medium">Why: </span>
        {item.error ? `The gate could not decide (${item.error}).` : item.reason}
        {item.confidence != null && <span className="text-gray-500"> ({Math.round(item.confidence * 100)}% sure)</span>}
      </div>
      <div className="rounded bg-gray-50 border border-gray-200 p-2 text-sm whitespace-pre-wrap">
        <div className="text-xs font-medium text-gray-500 mb-1">
          What the sender just wrote{item.quoted_chars ? ` (${item.quoted_chars} characters of older thread left out)` : ''}
        </div>
        {(item.new_text || '').slice(0, 1200) || '(empty)'}
      </div>
      <button type="button" className="text-xs text-primary-600" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Show'} the {item.history.length} earlier emails the gate was given
      </button>
      {open && (
        <ul className="text-xs text-gray-700 space-y-1">
          {item.history.length === 0 && <li>None: no earlier mail from this sender.</li>}
          {item.history.map((h, i) => (
            <li key={i}>
              [{i + 1}] {h.received} · {h.subject}
              {h.sub_type ? ` · ${h.sub_type} ${h.date || ''} ${h.time || ''}` : h.category ? ` · ${h.category}` : ''}
              {h.status ? ` · notice ${h.status}` : ''}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="flex-1 min-w-[12rem] border border-gray-300 rounded px-2 py-1 text-sm"
          placeholder="Note (optional): why?"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate('real')}
          className="px-3 py-1.5 rounded bg-green-600 text-white text-sm hover:bg-green-700 disabled:opacity-50"
        >
          Real interview news
        </button>
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate('not_real')}
          className="px-3 py-1.5 rounded bg-red-600 text-white text-sm hover:bg-red-700 disabled:opacity-50"
        >
          Not interview news
        </button>
        {item.human_decision && (
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate('clear')}
            className="px-3 py-1.5 rounded border border-gray-300 text-sm text-gray-700"
          >
            Undo
          </button>
        )}
      </div>
    </div>
  );
}

/** Shadow-mode test of the third interview screen: nothing here changes what students get. Mark each email; the totals show how far to trust the gate. */
export default function GateReview() {
  const [show, setShow] = useState('undecided');
  const list = useQuery({ queryKey: ['gateReviews', show], queryFn: () => apiClient.getGateReviews(show), staleTime: 0 });
  const summary = useQuery({ queryKey: ['gateSummary'], queryFn: () => apiClient.getGateSummary(), staleTime: 0 });
  const s = summary.data;
  const tiles: [string, number, string][] = s
    ? [
        ['To decide', s.undecided, 'text-gray-900'],
        ['Decided', s.decided, 'text-gray-900'],
        ['Gate agrees with you', s.agree, 'text-green-700'],
        ['Gate would hide a REAL one', s.hid_a_real_one, s.hid_a_real_one > 0 ? 'text-red-700' : 'text-gray-900'],
        ['Gate showed a non-interview', s.showed_a_non_interview, 'text-yellow-700'],
      ]
    : [];
  return (
    <div className="space-y-4">
      <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-900">
        Testing mode: the gate only gives its opinion. Nothing here sends, hides or changes a student notice. For each email, say whether it was
        really news about an interview (a new interview, a new round, a changed time, a cancellation).
        {s && <span> Gate mode on the server: <strong>{s.mode}</strong>.</span>}
      </div>
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">
          {tiles.map(([label, value, cls]) => (
            <div key={label} className="bg-white border border-gray-200 rounded-lg p-3">
              <div className={`text-2xl font-bold ${cls}`}>{value}</div>
              <div className="text-xs text-gray-500">{label}</div>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {SHOW.map((o) => (
          <button
            key={o.id}
            type="button"
            onClick={() => setShow(o.id)}
            className={`px-3 py-1 rounded-full text-sm ${show === o.id ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700'}`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {list.isLoading && <div className="text-sm text-gray-500">Loading…</div>}
      {list.data && list.data.length === 0 && <div className="text-sm text-gray-500">Nothing here.</div>}
      <div className="space-y-3">
        {(list.data ?? []).map((item) => <Row key={item.id} item={item} />)}
      </div>
    </div>
  );
}
