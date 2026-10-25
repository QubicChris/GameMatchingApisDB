import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Code, Group, Loader, Modal, Paper, Progress, ScrollArea, Stack, Table, Text, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCloudDownload } from '@tabler/icons-react';
import { api, ApiError } from '../api/client';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { formatNumber } from '../lib/format';
import { datesPercent, formatDuration, formatUtc, OUTCOME_COLOR, outcomeText } from '../lib/sofaSync';

const errMessage = (err: unknown) => (err instanceof Error ? err.message : String(err));

export function SofaSyncPage() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ['sofa-sync'],
    queryFn: api.sofaSync,
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 30000),
  });
  const s = status.data;

  const [startOpen, setStartOpen] = useState(false);
  const [stopOpen, setStopOpen] = useState(false);

  const plan = useQuery({ queryKey: ['sofa-sync-plan'], queryFn: api.sofaSyncPlan, enabled: startOpen, staleTime: 0 });

  const start = useMutation({
    mutationFn: api.startSofaSync,
    onSuccess: () => {
      setStartOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['sofa-sync'] });
      notifications.show({ color: 'teal', title: 'Sofa sync', message: 'Sofa sync started' });
    },
    onError: (err) => {
      notifications.show({
        color: 'red', title: 'Could not start',
        message: err instanceof ApiError ? err.message : errMessage(err),
      });
    },
  });

  const stop = useMutation({
    mutationFn: api.stopSofaSync,
    onSuccess: () => {
      setStopOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['sofa-sync'] });
    },
    onError: (err) => {
      setStopOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['sofa-sync'] });
      notifications.show({
        color: 'red', title: 'Could not stop',
        message: err instanceof ApiError ? err.message : errMessage(err),
      });
    },
  });

  // Total dates for the progress bar: captured on the first poll of each run (keyed by started_at).
  const totalRef = useRef<{ key: string; total: number } | null>(null);
  if (s?.running && s.started_here && s.started_at && totalRef.current?.key !== s.started_at) {
    totalRef.current = { key: s.started_at, total: s.window.dates };
  }

  // One notification when a run goes from running to idle.
  const prevRunning = useRef<boolean | null>(null);
  const notifiedRef = useRef<string | null>(null);
  const running = s?.running;
  const lastRun = s?.last_run ?? null;
  useEffect(() => {
    if (running === undefined) return;
    if (prevRunning.current === true && !running && lastRun && notifiedRef.current !== lastRun.finished_at) {
      notifiedRef.current = lastRun.finished_at;
      notifications.show({
        color: OUTCOME_COLOR[lastRun.outcome], title: 'Sofa sync', message: outcomeText(lastRun.outcome),
      });
    }
    prevRunning.current = running;
  }, [running, lastRun?.finished_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the log scrolled to the bottom.
  const viewportRef = useRef<HTMLDivElement>(null);
  const logLength = s?.log.length ?? 0;
  useEffect(() => {
    const el = viewportRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [logLength]);

  const quotaPct = s && s.quota.used != null && s.quota.limit ? (s.quota.used / s.quota.limit) * 100 : 0;
  const total = totalRef.current && s?.started_at === totalRef.current.key ? totalRef.current.total : (s?.window.dates ?? 0);
  const elapsed = s?.started_at ? (Date.now() - new Date(s.started_at).getTime()) / 1000 : 0;
  const p = plan.data;

  return (
    <>
      <PageHeader
        title="Sofa Sync"
        description="Match games to Sofasport and fetch their odds, statistics and incidents — day by day from the last completed date until caught up or the RapidAPI limit."
      />
      <QueryState query={status}>
        {s && (
          <Stack gap="md" maw={900}>
            <Paper withBorder p="lg">
              <Stack gap="sm">
                <Group>
                  {s.running ? (
                    <Badge color="teal" leftSection={<Loader size="xs" color="teal" />}>Running</Badge>
                  ) : (
                    <Badge color="gray">Idle</Badge>
                  )}
                </Group>

                <div>
                  <Title order={5} mb="xs">Quota</Title>
                  {s.quota.used == null || !s.quota.limit ? (
                    <Text size="sm" c="dimmed">Quota unavailable</Text>
                  ) : (
                    <>
                      <Progress
                        value={quotaPct} size="lg" mb="xs"
                        color={quotaPct > 90 ? 'red' : quotaPct > 70 ? 'yellow' : 'teal'}
                      />
                      <Text size="sm" c="dimmed" className="num">
                        {formatNumber(s.quota.used)} / {formatNumber(s.quota.limit)} calls this cycle
                        (since {s.quota.cycle_start}, resets on the 18th)
                      </Text>
                    </>
                  )}
                </div>

                <div>
                  <Text size="sm">Last completed date: {s.window.last_completed ?? '—'}</Text>
                  <Text size="sm">
                    {s.window.dates === 0
                      ? 'Nothing to do — caught up'
                      : `Next to process: ${s.window.start} → ${s.window.end} (${s.window.dates} dates)`}
                  </Text>
                </div>

                <Group>
                  <Button
                    leftSection={<IconCloudDownload size={18} />}
                    disabled={!s.can_start}
                    onClick={() => setStartOpen(true)}
                  >
                    Fetch Sofa events
                  </Button>
                  {s.running && s.started_here && (
                    <Button variant="light" color="red" onClick={() => setStopOpen(true)}>Stop</Button>
                  )}
                </Group>
                {!s.can_start && s.reason && <Text size="sm" c="dimmed">{s.reason}</Text>}
                {s.running && !s.started_here && (
                  <Alert color="blue">
                    A run is in progress that was started outside the dashboard (for example the daily scheduled
                    task). It can&apos;t be stopped from here.
                  </Alert>
                )}
              </Stack>
            </Paper>

            {s.running && s.started_here && (
              <Paper withBorder p="lg">
                <Title order={5} mb="xs">Progress</Title>
                <Text size="sm" c="dimmed" mb="sm">
                  Started by {s.started_by} at {s.started_at ? formatUtc(s.started_at) : '—'} UTC · running for{' '}
                  {formatDuration(elapsed)}
                </Text>
                <Progress value={datesPercent(s.dates_done_this_run, total)} size="lg" animated striped mb="xs" />
                <Text size="sm" className="num">
                  {s.dates_done_this_run ?? 0} of {total} dates done
                </Text>
                <Text size="sm" c="dimmed" className="num">
                  {formatNumber(s.calls_this_run ?? 0)} RapidAPI calls used by this run.
                </Text>
              </Paper>
            )}

            {s.log.length > 0 && (
              <Paper withBorder p="lg">
                <Title order={5} mb="sm">Log</Title>
                <ScrollArea h={320} viewportRef={viewportRef}>
                  <Code block>{s.log.join('\n')}</Code>
                </ScrollArea>
              </Paper>
            )}

            {!s.running && s.last_run && (
              <Text size="sm" c={OUTCOME_COLOR[s.last_run.outcome]}>
                Last run (started by {s.last_run.started_by}, {formatUtc(s.last_run.finished_at)} UTC):{' '}
                {outcomeText(s.last_run.outcome)}
              </Text>
            )}
          </Stack>
        )}
      </QueryState>

      <Modal opened={startOpen} onClose={() => setStartOpen(false)} size="lg" title="Fetch Sofa events">
        <QueryState query={plan}>
          {p && (
            <Stack gap="sm">
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Date</Table.Th>
                    <Table.Th style={{ textAlign: 'right' }}>Games</Table.Th>
                    <Table.Th style={{ textAlign: 'right' }}>To match</Table.Th>
                    <Table.Th style={{ textAlign: 'right' }}>Countries</Table.Th>
                    <Table.Th style={{ textAlign: 'right' }}>Max calls</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {p.rows.map((r) => (
                    <Table.Tr key={r.date}>
                      <Table.Td>{r.date}</Table.Td>
                      <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(r.games)}</Table.Td>
                      <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(r.to_match)}</Table.Td>
                      <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(r.countries)}</Table.Td>
                      <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(r.max_calls)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              <Text size="sm">
                Up to {formatNumber(p.max_calls_total)} RapidAPI calls (upper bound — assumes every game matches).{' '}
                {formatNumber(p.calls_left)} calls left this cycle.
              </Text>
              <Alert color="yellow">
                This uses paid RapidAPI quota. The run continues until it&apos;s caught up or the cycle limit (
                {formatNumber(p.quota.limit)} calls) is reached.
              </Alert>
            </Stack>
          )}
        </QueryState>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => setStartOpen(false)}>Cancel</Button>
          <Button loading={start.isPending} disabled={!p || plan.isFetching || plan.isError} onClick={() => start.mutate()}>Start</Button>
        </Group>
      </Modal>

      <Modal opened={stopOpen} onClose={() => setStopOpen(false)} title="Stop the run?">
        <Text size="sm">Stop the run? The date in progress will be redone next time.</Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => setStopOpen(false)}>Cancel</Button>
          <Button color="red" loading={stop.isPending} onClick={() => stop.mutate()}>Stop</Button>
        </Group>
      </Modal>
    </>
  );
}
