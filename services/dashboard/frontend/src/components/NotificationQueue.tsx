import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import type { CallbackItem, ReviewQueueItem } from '../types';

const VERDICT_STYLE: Record<string, { label: string; cls: string }> = {
  looks_genuine: { label: 'Looks like a real interview', cls: 'bg-green-100 text-green-800' },
  needs_check: { label: 'Check this email', cls: 'bg-yellow-100 text-yellow-800' },
  likely_job_board: { label: 'Looks like a job board', cls: 'bg-red-100 text-red-800' },
};

const STATE_LABEL: Record<string, { label: string; cls: string }> = {
  ready: { label: 'Ready for your decision', cls: 'bg-blue-100 text-blue-800' },
  needs_verification: { label: 'Verify the student first', cls: 'bg-orange-100 text-orange-800' },
  blocked: { label: 'Fix first', cls: 'bg-red-100 text-red-800' },
  needs_student: { label: 'Student not identified', cls: 'bg-red-100 text-red-800' },
  no_draft: { label: 'No draft', cls: 'bg-gray-100 text-gray-700' },
  approved: { label: 'Approved', cls: 'bg-green-100 text-green-800' },
  sent: { label: 'Sent', cls: 'bg-green-100 text-green-800' },
  rejected: { label: 'Rejected', cls: 'bg-gray-100 text-gray-700' },
};

const digits = (value?: string) => (value || '').replace(/\D/g, '');

const fmtWhen = (iso: string) => {
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  return d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' }) + ' CT';
};

/** One student who called back about an interview: the callback owner calls them and clicks "Called back". */
const CallbackRow = ({ cb }: { cb: CallbackItem }) => {
  const queryClient = useQueryClient();
  const done = useMutation({
    mutationFn: () => apiClient.markCalledBack(cb.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviewQueue'] });
      queryClient.invalidateQueries({ queryKey: ['interviewEvents'] });
    },
  });
  return (
    <li className={`p-3 rounded border text-sm flex flex-wrap items-start justify-between gap-3 ${cb.overdue ? 'bg-red-50 border-red-300' : 'bg-white border-red-200'}`}>
      <div className="space-y-1">
        <div className="font-semibold text-gray-900">
          {cb.student_name || 'Unknown caller'}
          {cb.overdue && <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-red-600 text-white">Overdue</span>}
        </div>
        <div className="text-gray-700">
          Called {fmtWhen(cb.received_at)} &middot; call back by <strong>{fmtWhen(cb.due_at)}</strong>
          {cb.caller_number && (
            <> &middot; <a className="text-primary-600 hover:underline" href={`tel:${digits(cb.caller_number)}`}>{cb.caller_number}</a></>
          )}
        </div>
        {cb.interviews.length > 0 && <div className="text-xs text-gray-600">Their interviews: {cb.interviews.join(' | ')}</div>}
        {cb.said && <div className="text-xs text-gray-500">They said: &ldquo;{cb.said.slice(0, 200)}&rdquo;</div>}
      </div>
      <button
        type="button"
        disabled={done.isPending}
        onClick={() => done.mutate()}
        className="px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50"
      >
        {done.isPending ? 'Saving...' : 'Called back'}
      </button>
    </li>
  );
};

const QueueCard = ({ item, escalationOn, callbacks }: { item: ReviewQueueItem; escalationOn: boolean; callbacks: CallbackItem[] }) => {
  const queryClient = useQueryClient();
  const [showEmail, setShowEmail] = useState(false);
  const [showWhy, setShowWhy] = useState(item.authenticity.verdict !== 'looks_genuine');
  const [showPreview, setShowPreview] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [editing, setEditing] = useState(false);
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editRecipient, setEditRecipient] = useState('');
  const [vName, setVName] = useState(item.student?.name || '');
  const [vPhone, setVPhone] = useState(item.student?.phone || '');
  const [vEmail, setVEmail] = useState(item.student?.personal_email || '');

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['reviewQueue'] });
    queryClient.invalidateQueries({ queryKey: ['pendingNotifications'] });
  };
  const approve = useMutation({
    mutationFn: (id: number) => apiClient.approveNotification(id),
    onSuccess: () => {
      setConfirming(false);
      refresh();
    },
  });
  const save = useMutation({
    mutationFn: (id: number) => apiClient.editNotification(id, editSubject, editBody, editRecipient, false),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const verify = useMutation({
    mutationFn: (id: number) => apiClient.verifyStudent(id, { full_name: vName, phone_number: vPhone, personal_email: vEmail }),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: (p: { id: number; reason?: string }) => apiClient.rejectNotification(p.id, p.reason),
    onSuccess: () => {
      setRejecting(false);
      refresh();
    },
  });

  const s = item.student;
  const myCallbacks = callbacks.filter((c) => s && c.student_id === s.id);
  const verdict = VERDICT_STYLE[item.authenticity.verdict] || VERDICT_STYLE.needs_check;
  const state = STATE_LABEL[item.state] || { label: item.state, cls: 'bg-gray-100 text-gray-700' };
  const iv = item.interview;
  const when = [iv.date, iv.time, iv.timezone].filter(Boolean).join(' ');
  const error = (approve.error || reject.error || save.error || verify.error) as { response?: { data?: { detail?: string } }; message?: string } | null;

  return (
    <li className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-5 py-4 space-y-4">
        {/* Who, and how to reach them */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-lg font-semibold text-gray-900">{s?.name || 'No student identified'}</div>
            {s ? (
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700">
                {s.phone ? (
                  <>
                    <a className="text-primary-600 hover:underline" href={`tel:${digits(s.phone)}`}>Call {s.phone}</a>
                    <a className="text-primary-600 hover:underline" href={`https://wa.me/${digits(s.phone)}`} target="_blank" rel="noreferrer">WhatsApp</a>
                  </>
                ) : (
                  <span className="text-red-700">No phone on file</span>
                )}
                {s.personal_email && (
                  <a className="text-primary-600 hover:underline" href={`mailto:${s.personal_email}`}>{s.personal_email}</a>
                )}
                {s.assigned_gmail && <span className="text-gray-500">Gmail: {s.assigned_gmail}</span>}
                {!s.personal_email && !s.assigned_gmail && <span className="text-red-700">No email on file</span>}
              </div>
            ) : (
              <div className="mt-1 text-sm text-gray-500">The student could not be worked out from this email.</div>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${state.cls}`}>{state.label}</span>
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${verdict.cls}`}>{verdict.label}</span>
          </div>
        </div>

        {myCallbacks.length > 0 && (
          <div className="p-2 bg-red-50 border border-red-300 rounded text-sm text-red-900">
            <strong>Callback needed:</strong> this student called back about an interview ({myCallbacks.map((c) => fmtWhen(c.received_at)).join(', ')}).
            Call them back, then click &ldquo;Called back&rdquo; in the Callbacks section at the top.
          </div>
        )}

        {/* Interview facts */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div><span className="block text-xs text-gray-500">Company</span>{iv.company || '—'}</div>
          <div><span className="block text-xs text-gray-500">Position</span>{iv.position || '—'}</div>
          <div><span className="block text-xs text-gray-500">When</span>{when || 'Not stated in the email'}</div>
          <div><span className="block text-xs text-gray-500">Format</span>{iv.format || '—'}</div>
        </div>

        {/* Is the email genuine? */}
        <div className="border border-gray-200 rounded-md">
          <button
            type="button"
            onClick={() => setShowWhy(!showWhy)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium text-gray-800"
          >
            <span>Is this email a real interview? {verdict.label}</span>
            <span className="text-gray-400">{showWhy ? 'Hide' : 'Why?'}</span>
          </button>
          {showWhy && (
            <div className="px-3 pb-3 space-y-2 text-sm">
              {item.authenticity.against.map((r) => (
                <div key={r} className="text-red-800">&bull; {r}</div>
              ))}
              {item.authenticity.for.map((r) => (
                <div key={r} className="text-green-800">&bull; {r}</div>
              ))}
              {item.authenticity.against.length === 0 && item.authenticity.for.length === 0 && (
                <div className="text-gray-600">Nothing conclusive either way.</div>
              )}
              <div className="text-xs text-gray-500">{item.authenticity.note}</div>
            </div>
          )}
        </div>

        {/* The source email */}
        {item.email && (
          <div className="text-sm">
            <div className="text-gray-700">
              <span className="text-xs text-gray-500">From </span>{item.email.from_address}
              <span className="text-xs text-gray-500"> &middot; </span>{item.email.subject}
            </div>
            <button type="button" className="text-primary-600 text-xs mt-1" onClick={() => setShowEmail(!showEmail)}>
              {showEmail ? 'Hide the start of the email' : 'Read the start of the email'}
            </button>
            {showEmail && (
              <div className="mt-2 p-3 bg-gray-50 border border-gray-200 rounded text-gray-700 whitespace-pre-wrap">
                {item.email.excerpt || 'No text stored for this email.'}
              </div>
            )}
          </div>
        )}

        {/* What the student will receive */}
        {item.preview && (
          <div className="text-sm">
            <button type="button" className="text-primary-600 text-xs" onClick={() => setShowPreview(!showPreview)}>
              {showPreview ? 'Hide what the student will receive' : 'See what the student will receive'}
            </button>
            {showPreview && (
              <div className="mt-2 space-y-2">
                <div className="p-3 bg-gray-50 border border-gray-200 rounded">
                  <div className="text-xs font-semibold text-gray-500 uppercase">Email: {item.preview.email_subject}</div>
                  <div className="whitespace-pre-wrap text-gray-700 mt-1">{item.draft?.body}</div>
                </div>
                <div className="p-3 bg-gray-50 border border-gray-200 rounded">
                  <div className="text-xs font-semibold text-gray-500 uppercase">Text message</div>
                  <div className="text-gray-700 mt-1">{item.preview.text}</div>
                </div>
                <div className="p-3 bg-gray-50 border border-gray-200 rounded">
                  <div className="text-xs font-semibold text-gray-500 uppercase">Facts given to the voice agent for the call</div>
                  <div className="text-gray-700 mt-1">{item.preview.call}</div>
                </div>
                {!escalationOn && (
                  <div className="text-xs text-gray-500">The text and call are previews only: they are not switched on yet.</div>
                )}
              </div>
            )}
          </div>
        )}

        {s && s.verification && s.verification.status !== 'verified' && (
          <div className="p-3 bg-orange-50 border border-orange-200 rounded space-y-2 text-sm">
            <div className="font-semibold text-orange-900">Verify who this student is</div>
            <div className="text-orange-900">
              The pipeline created this student from the email, so the name is a{' '}
              {s.verification.basis === 'greeting_name' ? 'guess from the greeting' : 'guess from the Gmail address'}
              . A candidate may have changed their email: trace them in the roster sheet or Drive and correct the details.
            </div>
            {s.verification.evidence && <div className="text-xs text-orange-800">{s.verification.evidence}</div>}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <label className="text-xs text-gray-600">
                Full name
                <input type="text" value={vName} onChange={(e) => setVName(e.target.value)} className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
              </label>
              <label className="text-xs text-gray-600">
                Phone
                <input type="text" value={vPhone} onChange={(e) => setVPhone(e.target.value)} placeholder="e.g. 312-555-0100" className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
              </label>
              <label className="text-xs text-gray-600">
                Personal email
                <input type="email" value={vEmail} onChange={(e) => setVEmail(e.target.value)} className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
              </label>
            </div>
            <button
              type="button"
              disabled={verify.isPending || !vName.trim()}
              onClick={() => verify.mutate(s.id)}
              className="px-4 py-2 bg-orange-600 text-white rounded-md text-sm font-medium hover:bg-orange-700 disabled:opacity-50"
            >
              {verify.isPending ? 'Saving...' : 'Confirm this student'}
            </button>
          </div>
        )}

        {item.blockers.map((b) => (
          <div key={b} className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-800">{b}</div>
        ))}
        {item.warnings.map((w) => (
          <div key={w} className="p-2 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-900">{w}</div>
        ))}

        {item.sequence && (
          <div className="text-sm text-gray-700">
            Follow-up status: <strong>{item.sequence.status}</strong>
            {item.sequence.ack_channel ? ` (confirmed by ${item.sequence.ack_channel})` : ''}
          </div>
        )}

        {/* Decision */}
        {item.draft_id !== null && item.state === 'ready' && (
          <div className="pt-3 border-t border-gray-100 space-y-2">
            {!confirming && !rejecting && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!item.can_approve}
                  onClick={() => setConfirming(true)}
                  className="px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditSubject(item.draft?.subject || '');
                    setEditBody(item.draft?.body || '');
                    setEditRecipient(item.draft?.recipient_email || '');
                    setEditing(true);
                  }}
                  className="px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-50"
                >
                  Edit draft
                </button>
                <button
                  type="button"
                  onClick={() => setRejecting(true)}
                  className="px-4 py-2 bg-white border border-red-300 text-red-700 rounded-md text-sm font-medium hover:bg-red-50"
                >
                  Reject
                </button>
              </div>
            )}
            {confirming && (
              <div className="p-3 bg-green-50 border border-green-200 rounded space-y-2">
                <div className="text-sm text-green-900">
                  Approving this will: <strong>{item.will_happen}</strong>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={approve.isPending}
                    onClick={() => approve.mutate(item.draft_id as number)}
                    className="px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                  >
                    {approve.isPending ? 'Working...' : 'Yes, approve'}
                  </button>
                  <button type="button" onClick={() => setConfirming(false)} className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm">
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {rejecting && (
              <div className="p-3 bg-red-50 border border-red-200 rounded space-y-2">
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why? (for example: job board, not a real interview)"
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={reject.isPending}
                    onClick={() => reject.mutate({ id: item.draft_id as number, reason: reason || undefined })}
                    className="px-4 py-2 bg-red-600 text-white rounded-md text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                  >
                    {reject.isPending ? 'Working...' : 'Reject this notification'}
                  </button>
                  <button type="button" onClick={() => setRejecting(false)} className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm">
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {editing && (
              <div className="p-3 bg-gray-50 border border-gray-200 rounded space-y-2">
                <input type="email" value={editRecipient} onChange={(e) => setEditRecipient(e.target.value)} placeholder="Recipient email"
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
                <input type="text" value={editSubject} onChange={(e) => setEditSubject(e.target.value)} placeholder="Subject"
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
                <textarea rows={8} value={editBody} onChange={(e) => setEditBody(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono" />
                <div className="flex gap-2">
                  <button type="button" disabled={save.isPending} onClick={() => save.mutate(item.draft_id as number)}
                    className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
                    {save.isPending ? 'Saving...' : 'Save changes'}
                  </button>
                  <button type="button" onClick={() => setEditing(false)} className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm">
                    Cancel
                  </button>
                </div>
                <div className="text-xs text-gray-500">Saving does not send anything. Approve when the draft is right.</div>
              </div>
            )}
            {error && (
              <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-800">
                {error.response?.data?.detail || error.message || 'Something went wrong. Nothing was changed.'}
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
};

/**
 * The approver's screen: every interview that needs a decision or a fix, with the student's contact details, an
 * advisory "is this a real interview?" check, a preview of what the student will receive, and Approve / Reject.
 */
const NotificationQueue = () => {
  const [showDone, setShowDone] = useState(false);
  const [onlyReady, setOnlyReady] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['reviewQueue', showDone],
    queryFn: () => apiClient.getReviewQueue(showDone),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  if (isLoading) {
    return <div className="py-10 text-center text-gray-500">Loading...</div>;
  }
  if (error || !data) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">
        Could not load the queue. <button type="button" className="underline" onClick={() => refetch()}>Try again</button>
      </div>
    );
  }

  const ready = data.items.filter((i) => i.state === 'ready').length;
  const fix = data.items.filter((i) => ['needs_verification', 'blocked', 'needs_student', 'no_draft'].includes(i.state)).length;
  const shown = onlyReady ? data.items.filter((i) => i.state === 'ready') : data.items;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-gray-700">
          <strong>{ready}</strong> ready for your decision &middot; <strong>{fix}</strong> need fixing before they can be approved
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => setOnlyReady(!onlyReady)} className="px-3 py-1.5 bg-white border border-gray-300 rounded-md text-sm">
            {onlyReady ? 'Show everything' : 'Only ready'}
          </button>
          <button type="button" onClick={() => setShowDone(!showDone)} className="px-3 py-1.5 bg-white border border-gray-300 rounded-md text-sm">
            {showDone ? 'Hide finished' : 'Show finished'}
          </button>
          <button type="button" onClick={() => refetch()} className="px-3 py-1.5 bg-primary-600 text-white rounded-md text-sm">
            Refresh
          </button>
        </div>
      </div>
      {(data.callbacks ?? []).length > 0 && (
        <div className="space-y-2">
          <h2 className="text-base font-bold text-red-800">Callbacks waiting ({data.callbacks.length})</h2>
          <p className="text-xs text-gray-600">
            These students called back about an interview. The AI receptionist only took the message: please call them back within one
            business hour, then click &ldquo;Called back&rdquo;.
          </p>
          <ul className="space-y-2">
            {data.callbacks.map((c) => <CallbackRow key={c.id} cb={c} />)}
          </ul>
        </div>
      )}
      {!data.escalation_enabled && (
        <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-900">
          Approving sends <strong>one email</strong> to the student. The call and text are not switched on yet.
        </div>
      )}
      {shown.length === 0 ? (
        <div className="py-10 text-center text-gray-500">Nothing needs a decision right now.</div>
      ) : (
        <ul className="space-y-4">
          {shown.map((item) => (
            <QueueCard key={`${item.event_id}-${item.draft_id}`} item={item} escalationOn={data.escalation_enabled} callbacks={data.callbacks ?? []} />
          ))}
        </ul>
      )}
    </div>
  );
};

export default NotificationQueue;
