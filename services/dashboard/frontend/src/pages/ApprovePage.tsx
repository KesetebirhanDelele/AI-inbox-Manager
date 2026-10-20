import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

/**
 * Opened from the link in an alert email: no login, the token in the URL is the key. Shows ONE card and asks for a second tap before anything happens.
 * Plain fetch (not the app's API client) so a bad link never redirects to the login page.
 */
type Card = {
  student: { name: string; phone?: string; personal_email?: string } | null;
  interview: { type?: string; company?: string; position?: string; date?: string; time?: string; timezone?: string; format?: string };
  email: { subject?: string; from_address?: string; received_date?: string; excerpt?: string } | null;
  authenticity: { verdict: string; note?: string };
  warnings: string[];
  blockers: string[];
  suggestion?: { action: string; text: string } | null;
  can_approve: boolean;
  will_happen: string;
  preview: { call: string; text: string; email_subject?: string } | null;
};
type View = { state: string; used_action?: string; draft_status?: string; delivery_live?: boolean; card?: Card };

const MESSAGES: Record<string, string> = {
  used: 'This link was already used.',
  expired: 'This link has expired. Open the Review page in the app instead.',
  decided: 'This card has already been decided. Nothing more to do.',
};

const ApprovePage = () => {
  const { token = '' } = useParams();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState<'approve' | 'reject' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'referrer';
    meta.content = 'no-referrer';
    document.head.appendChild(meta);
    return () => { document.head.removeChild(meta); };
  }, []);

  useEffect(() => {
    fetch(`/api/approve-links/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (r.status === 404) throw new Error('This link is not valid.');
        if (!r.ok) throw new Error('Could not load this card. Try again, or open the Review page in the app.');
        setView(await r.json());
      })
      .catch((e) => setError(e.message));
  }, [token]);

  const act = async (action: 'approve' | 'reject') => {
    setBusy(true);
    setActionError('');
    try {
      const r = await fetch(`/api/approve-links/${encodeURIComponent(token)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true, reason: action === 'reject' ? reason || undefined : undefined }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not complete this. Open the Review page in the app.');
      setDone(action === 'approve' ? 'Approved. The follow-up plan has started.' : 'Rejected. Nothing will be sent.');
    } catch (e) {
      setActionError((e as Error).message);
      setConfirming(null);
    } finally {
      setBusy(false);
    }
  };

  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-gray-100 px-4 py-6">
      <div className="max-w-xl mx-auto space-y-4">{children}</div>
    </div>
  );

  if (error) return shell(<div className="bg-white rounded-lg shadow p-4 text-red-800">{error}</div>);
  if (!view) return shell(<div className="bg-white rounded-lg shadow p-4 text-gray-600">Loading...</div>);
  if (done) return shell(<div className="bg-white rounded-lg shadow p-4 text-green-800 font-medium">{done}</div>);
  if (view.state !== 'ready' || !view.card) {
    return shell(<div className="bg-white rounded-lg shadow p-4 text-gray-800">{MESSAGES[view.state] || 'This link cannot be used.'}</div>);
  }

  const c = view.card;
  const iv = c.interview;
  const when = [iv.date, iv.time, iv.timezone].filter(Boolean).join(' ') || 'Not stated in the email';

  return shell(
    <>
      <div className="bg-white rounded-lg shadow p-4 space-y-2">
        <div className="text-lg font-semibold text-gray-900">{c.student?.name || 'Unknown student'}</div>
        <div className="text-sm text-gray-600">{[c.student?.phone || 'No phone on file', c.student?.personal_email].filter(Boolean).join(' · ')}</div>
        <dl className="text-sm grid grid-cols-3 gap-x-2 gap-y-1 pt-2">
          <dt className="text-gray-500">Type</dt><dd className="col-span-2">{iv.type || '—'}</dd>
          <dt className="text-gray-500">Company</dt><dd className="col-span-2">{iv.company || '—'}</dd>
          <dt className="text-gray-500">Position</dt><dd className="col-span-2">{iv.position || '—'}</dd>
          <dt className="text-gray-500">Interview time</dt><dd className="col-span-2">{when}</dd>
          <dt className="text-gray-500">Format</dt><dd className="col-span-2">{iv.format || '—'}</dd>
        </dl>
      </div>

      {c.suggestion && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-900">
          <strong>Suggested: {c.suggestion.action}.</strong> {c.suggestion.text}
        </div>
      )}
      {c.blockers.map((b) => <div key={b} className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">{b}</div>)}
      {c.warnings.map((w) => <div key={w} className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-900">{w}</div>)}

      {c.email && (
        <div className="bg-white rounded-lg shadow p-4 text-sm space-y-1">
          <div className="text-gray-500">From {c.email.from_address} · {c.email.subject}</div>
          <div className="whitespace-pre-wrap text-gray-800 max-h-48 overflow-y-auto">{c.email.excerpt}</div>
        </div>
      )}

      {c.preview && (
        <div className="bg-white rounded-lg shadow p-4 text-sm space-y-1">
          <div className="font-medium text-gray-900">What the student will receive</div>
          <div><span className="text-gray-500">Call: </span>{c.preview.call}</div>
          <div><span className="text-gray-500">Text: </span>{c.preview.text}</div>
          {c.preview.email_subject && <div><span className="text-gray-500">Email: </span>{c.preview.email_subject}</div>}
        </div>
      )}

      <div className={`rounded-lg p-3 text-sm ${view.delivery_live ? 'bg-red-50 border border-red-300 text-red-800' : 'bg-gray-50 border border-gray-200 text-gray-700'}`}>
        {view.delivery_live ? <strong>LIVE: </strong> : <strong>Shadow: </strong>}{c.will_happen}
      </div>

      {actionError && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">{actionError}</div>}

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        {confirming === null && (
          <div className="flex gap-3">
            <button type="button" disabled={!c.can_approve} onClick={() => setConfirming('approve')}
              className="flex-1 py-3 rounded-md bg-green-600 text-white font-medium disabled:opacity-40">Approve</button>
            <button type="button" onClick={() => setConfirming('reject')}
              className="flex-1 py-3 rounded-md border border-red-300 text-red-700 font-medium">Reject</button>
          </div>
        )}
        {confirming === 'approve' && (
          <div className="space-y-2">
            <div className="text-sm text-gray-900">Confirm: start the notification for <strong>{c.student?.name}</strong>? {view.delivery_live ? 'This calls, texts and emails them now.' : 'Shadow mode: nothing reaches them yet.'}</div>
            <div className="flex gap-3">
              <button type="button" disabled={busy} onClick={() => act('approve')} className="flex-1 py-3 rounded-md bg-green-600 text-white font-medium disabled:opacity-50">Yes, approve</button>
              <button type="button" onClick={() => setConfirming(null)} className="flex-1 py-3 rounded-md border border-gray-300">Cancel</button>
            </div>
          </div>
        )}
        {confirming === 'reject' && (
          <div className="space-y-2">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm" />
            <div className="flex gap-3">
              <button type="button" disabled={busy} onClick={() => act('reject')} className="flex-1 py-3 rounded-md bg-red-600 text-white font-medium disabled:opacity-50">Yes, reject</button>
              <button type="button" onClick={() => setConfirming(null)} className="flex-1 py-3 rounded-md border border-gray-300">Cancel</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default ApprovePage;
