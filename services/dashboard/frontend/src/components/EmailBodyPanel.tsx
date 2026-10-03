import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/**
 * Fetches and displays the full email body for an expanded email.
 */
const EmailBodyPanel = ({ emailId }: { emailId: number }) => {
  const [showFullBody, setShowFullBody] = useState(false);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['emailDetail', emailId],
    queryFn: () => apiClient.getEmailDetail(emailId),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="py-3 text-sm text-gray-500 italic">Could not load full email body.</div>
    );
  }

  const body = detail.email.full_body;
  if (!body) {
    return (
      <div className="py-3 text-sm text-gray-400 italic">No email body available.</div>
    );
  }

  const PREVIEW_LENGTH = 600;
  const isLong = body.length > PREVIEW_LENGTH;
  const displayBody = isLong && !showFullBody ? body.slice(0, PREVIEW_LENGTH) + '…' : body;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h5 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Email Body</h5>
        {detail.classifications && detail.classifications.length > 0 && (
          <div className="flex items-center gap-1">
            {detail.classifications.slice(0, 3).map((c, i) => (
              <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                {c.category} · {(c.confidence * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="bg-white border border-gray-200 rounded-md p-3">
        <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans break-words">
          {displayBody}
        </pre>
        {isLong && (
          <button
            onClick={() => setShowFullBody((v) => !v)}
            className="mt-2 text-xs text-primary-600 hover:underline"
          >
            {showFullBody ? 'Show less' : 'Show full email'}
          </button>
        )}
      </div>
    </div>
  );
};

export default EmailBodyPanel;
