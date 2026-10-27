import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { useSearchParams } from 'react-router-dom';
import ApprovalsContent from '../components/ApprovalsContent';
import NotificationQueue from '../components/NotificationQueue';
import GateReview from '../components/GateReview';

type TabType = 'notifications' | 'verify' | 'approvals' | 'gate';

const ReviewPage = () => {
  const [searchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<TabType>(
    requested === 'approvals' || requested === 'gate' ? requested : 'notifications',
  );

  // Same query the tabs use (cached), only to show how many students are waiting to be identified or verified.
  const queue = useQuery({ queryKey: ['reviewQueue', false], queryFn: () => apiClient.getReviewQueue(false), staleTime: 0 });
  const waitingCount = (queue.data?.items ?? []).filter((i) => ['needs_verification', 'needs_student'].includes(i.state)).length;

  const tabs: { id: TabType; name: string }[] = [
    { id: 'notifications', name: 'Student notifications' },
    { id: 'verify', name: waitingCount > 0 ? `Verify students (${waitingCount})` : 'Verify students' },
    { id: 'approvals', name: 'Classification review' },
    { id: 'gate', name: 'Gate review (testing)' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Review</h1>
        <p className="mt-1 text-sm text-gray-600">
          Approve student notifications and review low-confidence classifications
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm
                ${
                  activeTab === tab.id
                    ? 'border-primary-500 text-primary-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }
              `}
            >
              {tab.name}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div>
        {activeTab === 'notifications' && <NotificationQueue />}
        {activeTab === 'verify' && <NotificationQueue mode="verify" />}
        {activeTab === 'approvals' && <ApprovalsContent />}
        {activeTab === 'gate' && <GateReview />}
      </div>
    </div>
  );
};

export default ReviewPage;
