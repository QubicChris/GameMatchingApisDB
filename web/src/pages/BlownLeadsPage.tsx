import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge, Group, SegmentedControl, SimpleGrid, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFilter } from '@tabler/icons-react';
import type { ColumnDef } from '@tanstack/react-table';
import { api } from '../api/client';
import type { BlownLead } from '../api/types';
import { DataTable } from '../components/DataTable';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { StatCard } from '../components/StatCard';
import { DASH, formatKickoff, formatNumber, formatScore } from '../lib/format';

export function BlownLeadsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');

  const raw = Number(params.get('min') ?? '2');
  const min = Number.isFinite(raw) ? Math.min(5, Math.max(1, Math.round(raw))) : 2;

  const query = useQuery({ queryKey: ['blown-leads', min], queryFn: () => api.blownLeads(min) });
  const rows = query.data ?? [];
  const home = rows.filter((r) => r.scenario === 'home_blew_lead').length;

  const columns = useMemo<ColumnDef<BlownLead, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      {
        id: 'match_date', header: 'Date', accessorKey: 'match_date', meta: { align: 'left' },
        cell: ({ row }) => <span className="num">{formatKickoff(row.original.match_date)}</span>,
      },
      {
        id: 'home_name', header: 'Home', accessorKey: 'home_name', meta: { align: 'right' },
        cell: ({ row }) => <Text fw={500}>{row.original.home_name}</Text>,
      },
      {
        id: 'final', header: 'Final', accessorFn: (r) => r.score_home - r.score_away, meta: { align: 'center' },
        cell: ({ row }) => (
          <Badge variant="default" className="num">{formatScore(row.original.score_home, row.original.score_away)}</Badge>
        ),
      },
      {
        id: 'away_name', header: 'Away', accessorKey: 'away_name', meta: { align: 'left' },
        cell: ({ row }) => <Text fw={500}>{row.original.away_name}</Text>,
      },
      {
        id: 'lead', header: 'Lead', accessorFn: (r) => r.lead_time, meta: { align: 'left' },
        cell: ({ row }) => {
          const r = row.original;
          return r.lead_score_home != null && r.lead_score_away != null && r.lead_time != null
            ? <span className="num">{`${r.lead_score_home}–${r.lead_score_away} at ${r.lead_time}'`}</span>
            : DASH;
        },
      },
      {
        id: 'scenario', header: 'Scenario', accessorKey: 'scenario', meta: { align: 'left' },
        cell: ({ row }) =>
          row.original.scenario === 'home_blew_lead'
            ? <Badge color="orange" variant="light">Home blew lead</Badge>
            : <Badge color="grape" variant="light">Away blew lead</Badge>,
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Blown leads"
        description="Games where a team led by N+ goals at some point but didn't win."
        actions={
          <Group gap="xs">
            <Text size="sm">Min. lead</Text>
            <SegmentedControl
              value={String(min)}
              onChange={(v) => {
                const next = new URLSearchParams(params);
                next.set('min', v);
                setParams(next);
              }}
              data={['1', '2', '3', '4', '5']}
            />
          </Group>
        }
      />
      <SimpleGrid cols={{ base: 1, sm: 3 }} mb="md">
        <StatCard label="Games" value={formatNumber(rows.length)} />
        <StatCard label="Home blew lead" value={formatNumber(home)} />
        <StatCard label="Away blew lead" value={formatNumber(rows.length - home)} />
      </SimpleGrid>
      <TextInput
        mb="sm" w={280} placeholder="Filter by team…" leftSection={<IconFilter size={14} />}
        value={filter} onChange={(e) => setFilter(e.currentTarget.value)}
      />
      <QueryState query={query}>
        <DataTable<BlownLead>
          data={rows}
          columns={columns}
          globalFilter={filter}
          initialSorting={[{ id: 'match_date', desc: true }]}
          emptyText={`No games found with a blown ${min}+ goal lead.`}
          onRowClick={(r) => {
            if (r.game_id != null) navigate(`/games/${r.game_id}?tab=incidents`);
            else notifications.show({ message: 'This Sofa event is not linked to a game in the DB.' });
          }}
        />
      </QueryState>
    </>
  );
}
