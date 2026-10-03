import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import InboxContent from '../components/InboxContent';
import ApprovalsContent from '../components/ApprovalsContent';
import NotificationQueue from '../components/NotificationQueue';

type TabType = 'notifications' | 'inbox' | 'approvals';

const ReviewPage = () => {
  const [searchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<TabType>(
    requested === 'approvals' || requested === 'inbox' ? requested : 'notifications',
  );

  const tabs: { id: TabType; name: string }[] = [
    { id: 'notifications', name: 'Student notifications' },
    { id: 'inbox', name: 'Inbox' },
    { id: 'approvals', name: 'Classification review' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Review</h1>
        <p className="mt-1 text-sm text-gray-600">
          Approve student notifications, monitor inbox emails, and review low-confidence classifications
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
        {activeTab === 'inbox' && <InboxContent />}
        {activeTab === 'approvals' && <ApprovalsContent />}
      </div>
    </div>
  );
};

export default ReviewPage;
