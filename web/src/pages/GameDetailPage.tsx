import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Alert, Anchor, Badge, CopyButton, Grid, Group, Paper, Tabs, Text, Title, UnstyledButton,
} from '@mantine/core';
import {
  IconCalendar, IconChartBar, IconChartLine, IconListDetails, IconMapPin, IconTrophy,
} from '@tabler/icons-react';
import { ApiError, api } from '../api/client';
import { QueryState } from '../components/QueryState';
import { IncidentsTab } from '../features/game/IncidentsTab';
import { OddsTab } from '../features/game/OddsTab';
import { StatisticsTab } from '../features/game/StatisticsTab';
import { formatDateLong, formatKickoff, formatScore } from '../lib/format';

const TABS = ['odds', 'stats', 'incidents'];

function NotFound() {
  return (
    <Alert color="gray" title="Game not found">
      <Anchor component={Link} to="/games">← Back to games</Anchor>
    </Alert>
  );
}

export function GameDetailPage() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab = tabParam && TABS.includes(tabParam) ? tabParam : 'odds';

  const game = useQuery({
    queryKey: ['game', id],
    queryFn: () => api.game(id),
    enabled: Number.isFinite(id),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  if (!Number.isFinite(id)) return <NotFound />;
  if (game.error instanceof ApiError && game.error.status === 404) return <NotFound />;

  return (
    <QueryState query={game}>
      {game.data && (() => {
        const g = game.data;
        const date = g.kickoff.slice(0, 10);
        return (
          <>
            <Anchor component={Link} to={`/games?date=${date}`} size="sm">
              ← Back to {formatDateLong(date)}
            </Anchor>
            <Paper withBorder p="lg" mt="sm" mb="md">
              <Grid align="center">
                <Grid.Col span={{ base: 12, sm: 4 }}>
                  <Title order={3} ta={{ base: 'center', sm: 'right' }}>{g.home_team}</Title>
                </Grid.Col>
                <Grid.Col span={{ base: 12, sm: 4 }}>
                  <Text fz={40} fw={800} className="num" ta="center">{formatScore(g.score_home, g.score_away)}</Text>
                  <Group justify="center">
                    {g.sofa_status ? (
                      <Badge variant="light">{g.sofa_status}</Badge>
                    ) : (
                      <Badge color="gray" variant="light">Not matched to Sofa</Badge>
                    )}
                  </Group>
                </Grid.Col>
                <Grid.Col span={{ base: 12, sm: 4 }}>
                  <Title order={3} ta={{ base: 'center', sm: 'left' }}>{g.away_team}</Title>
                </Grid.Col>
              </Grid>
              <Group justify="center" gap="md" mt="sm" c="dimmed">
                <Group gap={4}>
                  <IconCalendar size={16} />
                  <Text size="sm" span>{formatKickoff(g.kickoff)}</Text>
                  <Text span size="xs">UTC</Text>
                </Group>
                <Group gap={4}><IconTrophy size={16} /><Text size="sm" span>{g.league}</Text></Group>
                {g.country && <Group gap={4}><IconMapPin size={16} /><Text size="sm" span>{g.country}</Text></Group>}
                {g.sofa_event_id != null && (
                  <CopyButton value={String(g.sofa_event_id)}>
                    {({ copied, copy }) => (
                      <UnstyledButton onClick={copy} aria-label="Copy Sofa event id">
                        <Badge variant="default" color="gray" style={{ cursor: 'pointer' }}>
                          {copied ? 'Copied' : `Sofa ${g.sofa_event_id}`}
                        </Badge>
                      </UnstyledButton>
                    )}
                  </CopyButton>
                )}
              </Group>
              {g.bookmakers.length > 0 && (
                <Group justify="center" gap="xs" mt="xs">
                  {g.bookmakers.map((b) => (
                    <Badge key={b} variant="outline">{b}</Badge>
                  ))}
                </Group>
              )}
            </Paper>
            <Tabs
              value={tab}
              onChange={(t) => setParams({ tab: t ?? 'odds' }, { replace: true })}
              keepMounted={false}
            >
              <Tabs.List mb="md">
                <Tabs.Tab value="odds" leftSection={<IconChartLine size={16} />}>Odds comparison</Tabs.Tab>
                <Tabs.Tab value="stats" leftSection={<IconChartBar size={16} />}>Statistics</Tabs.Tab>
                <Tabs.Tab value="incidents" leftSection={<IconListDetails size={16} />}>Incidents</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="odds"><OddsTab game={g} /></Tabs.Panel>
              <Tabs.Panel value="stats"><StatisticsTab game={g} /></Tabs.Panel>
              <Tabs.Panel value="incidents"><IncidentsTab game={g} /></Tabs.Panel>
            </Tabs>
          </>
        );
      })()}
    </QueryState>
  );
}
