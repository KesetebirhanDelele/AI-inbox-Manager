import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/**
 * The email behind an interview: collapsible, always with a visible heading so it never looks like it is missing.
 * Open by default; "Hide" folds it away, long emails show the first part with "Show full email".
 */
const EmailBodyPanel = ({ emailId }: { emailId: number }) => {
  const [open, setOpen] = useState(true);
  const [showFullBody, setShowFullBody] = useState(false);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['emailDetail', emailId],
    queryFn: () => apiClient.getEmailDetail(emailId),
    staleTime: 5 * 60 * 1000,
  });

  const body = detail?.email.full_body || '';
  const PREVIEW_LENGTH = 600;
  const isLong = body.length > PREVIEW_LENGTH;
  const displayBody = isLong && !showFullBody ? body.slice(0, PREVIEW_LENGTH) + '…' : body;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-xs font-semibold text-gray-700 uppercase tracking-wide"
          aria-expanded={open}
        >
          <svg className={`h-4 w-4 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Email body
          <span className="ml-1 font-normal normal-case text-primary-600">{open ? 'Hide' : 'Show'}</span>
        </button>
        {detail?.classifications && detail.classifications.length > 0 && (
          <div className="flex items-center gap-1">
            {detail.classifications.slice(0, 3).map((c, i) => (
              <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                {c.category} · {(c.confidence * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        )}
      </div>

      {open && (
        <div className="bg-white border border-gray-200 rounded-md p-3">
          {isLoading ? (
            <div className="flex justify-center py-2">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
            </div>
          ) : error || !detail ? (
            <p className="text-sm text-gray-500 italic">Could not load this email.</p>
          ) : !body ? (
            <p className="text-sm text-gray-500 italic">
              The text of this email was not stored, so there is nothing to show. Open the original message in Gmail
              (search for its subject) to read it.
            </p>
          ) : (
            <>
              <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans break-words">{displayBody}</pre>
              {isLong && (
                <button type="button" onClick={() => setShowFullBody((v) => !v)} className="mt-2 text-xs text-primary-600 hover:underline">
                  {showFullBody ? 'Show less' : 'Show full email'}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default EmailBodyPanel;
