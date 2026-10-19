import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Drawer, Group, NumberInput, Paper, Progress, Text, TextInput, Title } from '@mantine/core';
import { BarChart } from '@mantine/charts';
import { IconFilter } from '@tabler/icons-react';
import type { ColumnDef } from '@tanstack/react-table';
import { api } from '../api/client';
import type { CountryRate, LeagueRate } from '../api/types';
import { DataTable } from '../components/DataTable';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { formatNumber, formatPct, matchRateColor, ratioPct } from '../lib/format';

type Rate = { total: number; matched: number };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function rateColumns<T extends Rate>(nameId: string, nameHeader: string, nameKey: keyof T & string): ColumnDef<T, any>[] {
  return [
    {
      id: nameId, header: nameHeader, accessorKey: nameKey, meta: { align: 'left' },
      cell: ({ row }) => <Text fw={500}>{String(row.original[nameKey])}</Text>,
    },
    {
      id: 'total', header: 'Games', accessorKey: 'total', meta: { align: 'right' },
      cell: ({ row }) => <span className="num">{formatNumber(row.original.total)}</span>,
    },
    {
      id: 'matched', header: 'Matched', accessorKey: 'matched', meta: { align: 'right' },
      cell: ({ row }) => <span className="num">{formatNumber(row.original.matched)}</span>,
    },
    {
      id: 'unmatched', header: 'Unmatched', accessorFn: (r) => r.total - r.matched, meta: { align: 'right' },
      cell: ({ row }) => <span className="num">{formatNumber(row.original.total - row.original.matched)}</span>,
    },
    {
      id: 'rate', header: 'Match rate', accessorFn: (r) => ratioPct(r.matched, r.total), meta: { align: 'left' },
      cell: ({ row }) => {
        const pct = ratioPct(row.original.matched, row.original.total);
        return (
          <Group gap="xs" wrap="nowrap">
            <Progress w={120} value={pct} color={matchRateColor(pct)} />
            <Text size="sm" className="num">{formatPct(pct)}</Text>
          </Group>
        );
      },
    },
  ];
}

export function MatchRatesPage() {
  const query = useQuery({ queryKey: ['match-rates'], queryFn: api.matchRates });
  const [filter, setFilter] = useState('');
  const [minGames, setMinGames] = useState<number>(0);
  const [selected, setSelected] = useState<CountryRate | null>(null);

  const countries = query.data?.countries ?? [];
  const total = countries.reduce((s, c) => s + c.total, 0);
  const matched = countries.reduce((s, c) => s + c.matched, 0);

  const chartData = [...countries]
    .sort((a, b) => b.total - a.total)
    .slice(0, 15)
    .map((c) => ({ country: c.country, Matched: c.matched, Unmatched: c.total - c.matched }));

  const visible = useMemo(() => countries.filter((c) => c.total >= minGames), [countries, minGames]);
  const countryCols = useMemo(() => rateColumns<CountryRate>('country', 'Country', 'country'), []);
  const leagueCols = useMemo(() => rateColumns<LeagueRate>('league', 'League', 'league'), []);
  const leagues = useMemo(
    () => (query.data?.leagues ?? []).filter((l) => l.country === selected?.country),
    [query.data, selected],
  );
  const selPct = selected ? ratioPct(selected.matched, selected.total) : 0;

  return (
    <>
      <PageHeader
        title="Match rates"
        description={`${countries.length} countries · ${formatNumber(matched)}/${formatNumber(total)} matched overall (${formatPct(ratioPct(matched, total))})`}
      />
      <QueryState query={query}>
        <Paper withBorder p="md" radius="md" mb="md">
          <Title order={5} mb="sm">Biggest countries by volume</Title>
          <BarChart
            h={320}
            data={chartData}
            dataKey="country"
            orientation="vertical"
            type="stacked"
            series={[
              { name: 'Matched', color: 'teal.6' },
              { name: 'Unmatched', color: 'gray.6' },
            ]}
            yAxisProps={{ width: 110 }}
            withLegend
          />
        </Paper>
        <Group mb="sm" align="flex-end">
          <TextInput
            placeholder="Filter countries…" leftSection={<IconFilter size={14} />}
            value={filter} onChange={(e) => setFilter(e.currentTarget.value)}
          />
          <NumberInput
            label="Min. games" min={0} w={120} value={minGames}
            onChange={(v) => setMinGames(typeof v === 'number' ? v : 0)}
          />
        </Group>
        <DataTable<CountryRate>
          data={visible}
          columns={countryCols}
          globalFilter={filter}
          pageSize={100}
          initialSorting={[{ id: 'rate', desc: true }]}
          onRowClick={setSelected}
          emptyText="No countries match."
        />
      </QueryState>
      <Drawer
        opened={selected != null}
        onClose={() => setSelected(null)}
        position="right"
        size="lg"
        title={selected ? `${selected.country} — ${selected.matched}/${selected.total} matched (${formatPct(selPct)})` : ''}
      >
        <DataTable<LeagueRate>
          data={leagues}
          columns={leagueCols}
          pageSize={100}
          initialSorting={[{ id: 'rate', desc: true }]}
          emptyText="No leagues."
        />
      </Drawer>
    </>
  );
}
