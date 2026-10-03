// One place for how an interview type is shown (keys are what normalize_sub_type returns in the API).
export const TYPE_STYLES: Record<string, string> = {
  interview_request: 'bg-blue-100 text-blue-800',
  phone_screen: 'bg-green-100 text-green-800',
  client_screen: 'bg-purple-100 text-purple-800',
  technical_interview: 'bg-yellow-100 text-yellow-800',
  interview_schedule: 'bg-teal-100 text-teal-800',
  confirmed: 'bg-emerald-100 text-emerald-800',
  assessment: 'bg-cyan-100 text-cyan-800',
  final_round: 'bg-fuchsia-100 text-fuchsia-800',
  cancelled: 'bg-red-100 text-red-800',
  rescheduled: 'bg-orange-100 text-orange-800',
  job_machine: 'bg-indigo-100 text-indigo-800',
  other: 'bg-gray-100 text-gray-700',
};

export const TYPE_LABELS: Record<string, string> = {
  interview_request: 'Interview Request',
  phone_screen: 'Phone Screen',
  client_screen: 'Client Screen',
  technical_interview: 'Technical Interview',
  interview_schedule: 'Interview Scheduled',
  confirmed: 'Interview Confirmed',
  assessment: 'Assessment',
  final_round: 'Final Round',
  cancelled: 'Cancelled',
  rescheduled: 'Rescheduled',
  job_machine: 'Job Machine',
  other: 'Other interview email',
};
