import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Button, ColorSwatch, Group, Modal, Paper, SegmentedControl, SimpleGrid, Stack, Text,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconCloudDownload, IconInfoCircle } from '@tabler/icons-react';
import { api } from '../../api/client';
import type { GameDetail, GameStatistics } from '../../api/types';
import { QueryState } from '../../components/QueryState';
import { StatCompareRow } from './StatCompareRow';
import { PERIOD_LABELS, STAT_GROUPS, groupRows } from './statGroups';

export function StatisticsTab({ game }: { game: GameDetail }) {
  const matched = game.sofa_event_id != null;
  const queryClient = useQueryClient();
  const [modalOpen, { open, close }] = useDisclosure(false);
  const [period, setPeriod] = useState<string | null>(null);

  const stats = useQuery({
    queryKey: ['statistics', game.id],
    queryFn: () => api.statistics(game.id),
    enabled: matched,
  });
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary, enabled: matched });

  const fetchMutation = useMutation({
    mutationFn: () => api.fetchStatistics(game.id),
    onSuccess: (data: GameStatistics) => {
      queryClient.setQueryData(['statistics', game.id], data);
      queryClient.invalidateQueries({ queryKey: ['summary'] });
      close();
      if (data.periods.length > 0) {
        notifications.show({ color: 'green', title: 'Statistics fetched', message: 'Statistics stored for this game.' });
      } else {
        notifications.show({ color: 'yellow', title: 'No statistics', message: 'Sofasport returned no statistics for this game' });
      }
    },
    onError: (err: Error) => {
      close();
      notifications.show({ color: 'red', title: 'Fetch failed', message: err.message });
    },
  });

  if (!matched) {
    return (
      <Alert color="gray" icon={<IconInfoCircle />}>
        No Sofasport match — statistics unavailable.
      </Alert>
    );
  }

  const used = summary.data?.api_calls_used;
  const limit = summary.data?.api_call_limit;

  return (
    <QueryState query={stats}>
      {(stats.data?.periods.length ?? 0) === 0 ? (
        <Paper withBorder p="xl">
          <Stack align="center" gap="sm">
            <Text c="dimmed">No statistics stored for this game.</Text>
            <Button leftSection={<IconCloudDownload size={16} />} onClick={open} loading={fetchMutation.isPending}>
              Fetch from Sofasport
            </Button>
          </Stack>
          <Modal opened={modalOpen} onClose={close} title="Fetch statistics from Sofasport" centered>
            <Text size="sm">This makes 1 RapidAPI call.</Text>
            {used != null && limit != null && (
              <Text size="sm" c="dimmed" mt="xs">{`${limit - used} of ${limit} calls left this cycle.`}</Text>
            )}
            <Group justify="flex-end" mt="lg">
              <Button variant="default" onClick={close}>Cancel</Button>
              <Button loading={fetchMutation.isPending} onClick={() => fetchMutation.mutate()}>
                Fetch
              </Button>
            </Group>
          </Modal>
        </Paper>
      ) : (
        <StatsBody game={game} data={stats.data!} period={period} setPeriod={setPeriod} />
      )}
    </QueryState>
  );
}

function StatsBody({
  game, data, period, setPeriod,
}: { game: GameDetail; data: GameStatistics; period: string | null; setPeriod: (p: string) => void }) {
  const active = period && data.periods.includes(period) ? period : data.periods.includes('ALL') ? 'ALL' : data.periods[0];
  const periodStats = data.stats[active] ?? {};
  return (
    <>
      <SegmentedControl
        mb="md"
        value={active}
        onChange={setPeriod}
        data={data.periods.map((p) => ({ value: p, label: PERIOD_LABELS[p] ?? p }))}
      />
      <Group justify="space-between" mb="md">
        <Group gap="xs"><ColorSwatch color="var(--mantine-color-teal-6)" size={12} /><Text fw={600}>{game.home_team}</Text></Group>
        <Group gap="xs"><Text fw={600}>{game.away_team}</Text><ColorSwatch color="var(--mantine-color-orange-6)" size={12} /></Group>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {STAT_GROUPS.map((g) => ({ g, rows: groupRows(g, periodStats) }))
          .filter(({ rows }) => rows.length > 0)
          .map(({ g, rows }) => (
            <Paper key={g.name} withBorder p="md">
              <Text fw={600} mb="xs">{g.name}</Text>
              {rows.map((r) => (
                <StatCompareRow
                  key={r.def.key} label={r.def.label} kind={r.def.kind}
                  home={r.home} away={r.away} homeTotal={r.homeTotal} awayTotal={r.awayTotal}
                />
              ))}
            </Paper>
          ))}
      </SimpleGrid>
    </>
  );
}
