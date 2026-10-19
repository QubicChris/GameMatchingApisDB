import { Anchor, Grid, Group, Paper, Progress, RingProgress, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { BarChart } from '@mantine/charts';
import { IconBallFootball, IconWorld } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { StatCard } from '../components/StatCard';
import { formatNumber, formatPct, matchRateColor, ratioPct } from '../lib/format';

export function OverviewPage() {
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary });
  const daily = useQuery({ queryKey: ['daily', 30], queryFn: () => api.daily(30) });
  const rates = useQuery({ queryKey: ['match-rates'], queryFn: api.matchRates });

  const s = summary.data;
  const lowest = (rates.data?.countries ?? [])
    .filter((c) => c.total >= 20)
    .map((c) => ({ ...c, pct: ratioPct(c.matched, c.total) }))
    .sort((a, b) => a.pct - b.pct)
    .slice(0, 8);

  const chartData = (daily.data ?? []).map((d) => ({
    date: dayjs(d.date).format('DD MMM'),
    Matched: d.matched,
    Unmatched: d.total - d.matched,
  }));

  return (
    <>
      <PageHeader
        title="Overview"
        description="Everything ingested so far — games, Sofasport match coverage and API quota."
      />
      <Stack gap="md">
        <QueryState query={summary}>
          {s && (
            <>
              <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }}>
                <StatCard
                  label="Games"
                  value={formatNumber(s.total_games)}
                  hint={`${s.date_from ?? '—'} → ${s.date_to ?? '—'}`}
                  icon={<IconBallFootball size={18} />}
                />
                <StatCard
                  label="Sofa matched"
                  value={
                    <Group justify="space-between" wrap="nowrap">
                      <span>{formatPct(s.match_pct, 1)}</span>
                      <RingProgress
                        size={56}
                        thickness={6}
                        sections={[{ value: s.match_pct, color: matchRateColor(s.match_pct) }]}
                      />
                    </Group>
                  }
                  hint={`${formatNumber(s.matched)} of ${formatNumber(s.total_games)} games`}
                />
                <StatCard
                  label="Unmatched"
                  value={formatNumber(s.unmatched)}
                  hint={
                    <Anchor component={Link} to="/games?sofa=unmatched" size="sm">
                      Show unmatched games
                    </Anchor>
                  }
                />
                <StatCard
                  label="Coverage"
                  value={`${formatNumber(s.countries)} countries`}
                  hint={`${formatNumber(s.bookmakers)} bookmakers`}
                  icon={<IconWorld size={18} />}
                />
              </SimpleGrid>

              <Paper withBorder p="md" radius="md">
                <Title order={5} mb="sm">RapidAPI quota</Title>
                {s.api_calls_used == null ? (
                  <Text c="dimmed" size="sm">Quota unavailable (api_call_log not readable)</Text>
                ) : (
                  (() => {
                    const pct = (s.api_calls_used / s.api_call_limit) * 100;
                    return (
                      <>
                        <Progress
                          value={pct}
                          color={pct > 90 ? 'red' : pct > 70 ? 'yellow' : 'teal'}
                          size="lg"
                          mb="xs"
                        />
                        <Text size="sm" c="dimmed" className="num">
                          {formatNumber(s.api_calls_used)} / {formatNumber(s.api_call_limit)} calls this cycle
                          (since {s.api_cycle_start}, resets on the 18th)
                        </Text>
                      </>
                    );
                  })()
                )}
              </Paper>
            </>
          )}
        </QueryState>

        <Grid>
          <Grid.Col span={{ base: 12, lg: 8 }}>
            <Paper withBorder p="md" radius="md" h="100%">
              <Title order={5} mb="sm">Games per day (last 30 dates)</Title>
              <QueryState query={daily} empty={chartData.length === 0} emptyText="No games yet.">
                <BarChart
                  h={280}
                  data={chartData}
                  dataKey="date"
                  type="stacked"
                  series={[
                    { name: 'Matched', color: 'teal.6' },
                    { name: 'Unmatched', color: 'gray.6' },
                  ]}
                  withLegend
                />
              </QueryState>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, lg: 4 }}>
            <Paper withBorder p="md" radius="md" h="100%">
              <Title order={5} mb="sm">Lowest match rates</Title>
              <QueryState query={rates} empty={lowest.length === 0} emptyText="No countries with 20+ games.">
                <Stack gap="sm">
                  {lowest.map((c) => (
                    <div key={c.country}>
                      <Group justify="space-between" mb={2} wrap="nowrap">
                        <Text size="sm" truncate>{c.country}</Text>
                        <Text size="xs" c="dimmed" className="num">{c.matched}/{c.total}</Text>
                      </Group>
                      <Progress value={c.pct} color={matchRateColor(c.pct)} size="sm" />
                    </div>
                  ))}
                  <Anchor component={Link} to="/match-rates" size="sm">
                    View all countries →
                  </Anchor>
                </Stack>
              </QueryState>
            </Paper>
          </Grid.Col>
        </Grid>
      </Stack>
    </>
  );
}
