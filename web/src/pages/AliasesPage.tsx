import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Text, TextInput, useComputedColorScheme } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import type { ColumnDef } from '@tanstack/react-table';
import { api } from '../api/client';
import type { AliasRow } from '../api/types';
import { DataTable } from '../components/DataTable';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { DASH } from '../lib/format';

export function AliasesPage() {
  const [params, setParams] = useSearchParams();
  const urlQ = params.get('q') ?? '';
  const [input, setInput] = useState(urlQ);
  const [q] = useDebouncedValue(input, 300);
  const scheme = useComputedColorScheme('light');

  useEffect(() => {
    if (q === urlQ) return;
    const next = new URLSearchParams(params);
    if (q) next.set('q', q);
    else next.delete('q');
    setParams(next, { replace: true });
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const query = useQuery({
    queryKey: ['aliases', q],
    queryFn: () => api.aliases(q),
    placeholderData: (prev) => prev,
  });
  const sources = query.data?.sources ?? [];
  const rows = query.data?.rows ?? [];
  const highlight = scheme === 'dark' ? 'yellow.5' : 'yellow.8';

  const columns = useMemo<ColumnDef<AliasRow, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      {
        id: 'canonical_name', header: 'Team (canonical)', accessorKey: 'canonical_name', meta: { align: 'left' },
        cell: ({ row }) => <Text fw={600}>{row.original.canonical_name}</Text>,
      },
      ...sources.map((source): ColumnDef<AliasRow, any> => ({ // eslint-disable-line @typescript-eslint/no-explicit-any
        id: source,
        header: source,
        accessorFn: (r) => r.names[source] ?? '',
        meta: { align: 'left' },
        cell: ({ row }) => {
          const name = row.original.names[source] ?? '';
          if (!name) return <Text c="dimmed">{DASH}</Text>;
          if (name.trim().toLowerCase() === row.original.canonical_name.trim().toLowerCase()) {
            return <Text c="dimmed">{name}</Text>;
          }
          return <Text c={highlight} fw={500}>{name}</Text>;
        },
      })),
    ],
    [sources, highlight],
  );

  return (
    <>
      <PageHeader
        title="Team aliases"
        description="How each source names the same team. Names that differ from the canonical name are highlighted."
      />
      <TextInput
        mb="sm" w={320} placeholder="Search teams…" leftSection={<IconSearch size={14} />}
        value={input} onChange={(e) => setInput(e.currentTarget.value)}
      />
      <QueryState query={query}>
        <DataTable<AliasRow> data={rows} columns={columns} pageSize={100} emptyText="No teams found." />
        <Text size="sm" c="dimmed" mt="xs">{rows.length} team(s)</Text>
      </QueryState>
    </>
  );
}
