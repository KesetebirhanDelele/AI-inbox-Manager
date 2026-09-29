import { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';

// h:mm:ss once the wait is an hour or more (the real schedule is every 2 hours,
// so "90:28" would be hard to read); m:ss below an hour.
const formatDuration = (ms: number): string => {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = (totalSeconds % 60).toString().padStart(2, '0');
  return hours > 0
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${seconds}`
    : `${minutes}:${seconds}`;
};

export const useCountdownTimer = () => {
  const queryClient = useQueryClient();
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);

  const { data: scheduleConfig } = useQuery({
    queryKey: ['scheduleConfig'],
    queryFn: () => apiClient.getScheduleConfig(),
  });

  useEffect(() => {
    if (!scheduleConfig?.interval_minutes) {
      setTimeRemaining(null);
      return;
    }

    const intervalMs = scheduleConfig.interval_minutes * 60 * 1000;

    // The real cron job fires on fixed UTC clock boundaries (crontab:
    // `0 */2 * * *` -- 00:00, 02:00, 04:00 UTC, ...), independent of when any
    // particular run happened. Anchoring this to `last_run_timestamp` (as a
    // previous version did) meant every manual "Run Now" click rewrote the
    // anchor and permanently desynced the countdown from the real schedule.
    // Unix epoch is itself UTC-midnight-aligned and every offered interval
    // (5/10/15/30/60/120 min) divides evenly into it, so rounding up to the
    // next multiple of intervalMs always lands exactly on the true boundary.
    const computeNextRun = (): Date => {
      const now = new Date();
      return new Date(Math.ceil(now.getTime() / intervalMs) * intervalMs);
    };

    const updateCountdown = () => {
      const now = new Date();
      const nextRun = computeNextRun();
      const remaining = nextRun.getTime() - now.getTime();

      if (remaining <= 0) {
        // Boundary just passed — trigger a refresh and wait for the next one
        queryClient.invalidateQueries({ queryKey: ['summaryStats'] });
        queryClient.invalidateQueries({ queryKey: ['processingRuns'] });
        setTimeRemaining(intervalMs);
      } else {
        setTimeRemaining(remaining);
      }
    };

    updateCountdown();
    const interval = setInterval(updateCountdown, 1000);
    return () => clearInterval(interval);
  }, [scheduleConfig?.interval_minutes, queryClient]);

  return {
    timeRemaining,
    formatted: timeRemaining ? formatDuration(timeRemaining) : null,
    isRunning: timeRemaining !== null && timeRemaining > 0,
    isScheduled: !!scheduleConfig?.interval_minutes,
    intervalMinutes: scheduleConfig?.interval_minutes,
  };
};
