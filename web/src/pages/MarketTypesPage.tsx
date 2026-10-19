import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Badge, Group, Switch, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import type { ColumnDef } from '@tanstack/react-table';
import { api } from '../api/client';
import type { MarketType } from '../api/types';
import { DataTable } from '../components/DataTable';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { DASH, formatKickoff } from '../lib/format';

const when = (iso: string | null) => (iso ? <span className="num">{formatKickoff(iso)}</span> : DASH);

export function MarketTypesPage() {
  const query = useQuery({ queryKey: ['market-types'], queryFn: api.marketTypes });
  const [filter, setFilter] = useState('');
  const [onlyMissing, setOnlyMissing] = useState(false);

  const all = query.data ?? [];
  const missing = all.filter((m) => !m.canonical_name).length;
  const rows = onlyMissing ? all.filter((m) => !m.canonical_name) : all;

  const columns = useMemo<ColumnDef<MarketType, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      {
        id: 'umid', header: 'Market ID', accessorKey: 'umid', meta: { align: 'right' },
        cell: ({ row }) => <span className="num">{row.original.umid}</span>,
      },
      {
        id: 'canonical_name', header: 'Name', accessorFn: (m) => m.canonical_name ?? '', meta: { align: 'left' },
        cell: ({ row }) =>
          row.original.canonical_name ?? <Badge color="yellow" variant="light">No name yet</Badge>,
      },
      {
        id: 'first_seen_at', header: 'First seen (UTC)', accessorFn: (m) => m.first_seen_at ?? '', meta: { align: 'left' },
        cell: ({ row }) => when(row.original.first_seen_at),
      },
      {
        id: 'last_updated_at', header: 'Last updated (UTC)', accessorFn: (m) => m.last_updated_at ?? '', meta: { align: 'left' },
        cell: ({ row }) => when(row.original.last_updated_at),
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Market types"
        description={`${all.length} market types · ${missing} with no canonical name yet`}
      />
      <Group mb="sm">
        <TextInput
          placeholder="Search…" leftSection={<IconSearch size={14} />}
          value={filter} onChange={(e) => setFilter(e.currentTarget.value)}
        />
        <Switch label="Only missing names" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.currentTarget.checked)} />
      </Group>
      <QueryState query={query}>
        <DataTable<MarketType>
          data={rows}
          columns={columns}
          globalFilter={filter}
          pageSize={100}
          initialSorting={[{ id: 'umid', desc: false }]}
          emptyText="No market types."
        />
      </QueryState>
    </>
  );
}
