import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Badge, Chip, Group, SegmentedControl, Text, ThemeIcon, Timeline } from '@mantine/core';
import {
  IconArrowsExchange, IconBallFootball, IconCards, IconClockHour4, IconClockPlus, IconDeviceTv,
  IconInfoCircle, IconPoint,
} from '@tabler/icons-react';
import type { ComponentType } from 'react';
import { api } from '../../api/client';
import type { GameDetail } from '../../api/types';
import { QueryState } from '../../components/QueryState';
import { incidentMinute } from '../../lib/format';
import { INCIDENT_FILTERS, describeIncident, incidentTeam, type IncidentKind } from './incidents';

const ICONS: Record<IncidentKind, ComponentType<{ size?: number }>> = {
  goal: IconBallFootball,
  card: IconCards,
  substitution: IconArrowsExchange,
  var: IconDeviceTv,
  period: IconClockHour4,
  injuryTime: IconClockPlus,
  other: IconPoint,
};

export function IncidentsTab({ game }: { game: GameDetail }) {
  const matched = game.sofa_event_id != null;
  const incidents = useQuery({
    queryKey: ['incidents', game.id],
    queryFn: () => api.incidents(game.id),
    enabled: matched,
  });
  const [kinds, setKinds] = useState<string[]>(INCIDENT_FILTERS.map((f) => f.value));
  const [order, setOrder] = useState<string>('oldest');

  const visible = useMemo(() => {
    const list = (incidents.data ?? [])
      .map((i) => ({ i, view: describeIncident(i) }))
      .filter(({ view }) => view.kind === 'other' || kinds.includes(view.kind));
    return order === 'newest' ? [...list].reverse() : list;
  }, [incidents.data, kinds, order]);

  if (!matched) {
    return (
      <Alert color="gray" icon={<IconInfoCircle />}>
        No Sofasport match — incidents unavailable.
      </Alert>
    );
  }

  return (
    <QueryState
      query={incidents}
      empty={(incidents.data?.length ?? 0) === 0}
      emptyText="No incidents recorded for this game."
    >
      <Group mb="md" justify="space-between">
        <Chip.Group multiple value={kinds} onChange={setKinds}>
          <Group gap="xs">
            {INCIDENT_FILTERS.map((f) => (
              <Chip key={f.value} value={f.value} size="xs">{f.label}</Chip>
            ))}
          </Group>
        </Chip.Group>
        <SegmentedControl
          value={order} onChange={setOrder}
          data={[{ label: 'Oldest first', value: 'oldest' }, { label: 'Newest first', value: 'newest' }]}
        />
      </Group>
      <Timeline active={-1} bulletSize={28} lineWidth={2}>
        {visible.map(({ i, view }, idx) => {
          const Icon = ICONS[view.kind];
          const team = incidentTeam(i, game.home_team, game.away_team);
          const showScore = (view.kind === 'goal' || view.kind === 'period') && i.home_score != null && i.away_score != null;
          return (
            <Timeline.Item
              key={idx}
              bullet={
                <ThemeIcon radius="xl" size={28} color={view.color} variant="light">
                  <Icon size={16} />
                </ThemeIcon>
              }
              title={
                <Group gap="xs">
                  <Badge variant="default" className="num">{incidentMinute(i.time, i.added_time)}</Badge>
                  <Text fw={600} span>{view.label}</Text>
                  {team && <Badge variant="light" color={i.is_home ? 'teal' : 'orange'}>{team}</Badge>}
                </Group>
              }
            >
              <Group gap="xs">
                {view.detail && <Text size="sm" c="dimmed">{view.detail}</Text>}
                {showScore && <Badge variant="outline" className="num">{`${i.home_score} – ${i.away_score}`}</Badge>}
              </Group>
            </Timeline.Item>
          );
        })}
      </Timeline>
    </QueryState>
  );
}
