import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ActionIcon, Badge, CloseButton, Group, Paper, SegmentedControl, Select, Text, TextInput, Tooltip,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconChevronLeft, IconChevronRight, IconFilter } from '@tabler/icons-react';
import type { ColumnDef } from '@tanstack/react-table';
import dayjs from 'dayjs';
import { api } from '../api/client';
import type { GameRow, SofaFilter } from '../api/types';
import { DataTable } from '../components/DataTable';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { formatDateLong, formatKickoff, formatScore, formatTime } from '../lib/format';

export function GamesPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [localFilter, setLocalFilter] = useState('');

  const date = params.get('date') ?? undefined;
  const country = params.get('country') ?? undefined;
  const sofa = (params.get('sofa') as SofaFilter | null) ?? 'all';
  const q = params.get('q') ?? undefined;

  const filters = useQuery({ queryKey: ['filters'], queryFn: api.filters });
  const dates = filters.data?.dates ?? [];
  const dateSet = useMemo(() => new Set(dates), [dates]);

  const update = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === undefined || v === '') next.delete(k);
      else next.set(k, v);
    }
    setParams(next);
  };

  useEffect(() => {
    if (!date && !q && dates.length > 0) {
      const next = new URLSearchParams(params);
      next.set('date', dates[0]);
      setParams(next, { replace: true });
    }
  }, [date, q, dates, params, setParams]);

  const searchMode = !date && (q?.length ?? 0) >= 2;
  const games = useQuery({
    queryKey: ['games', date, country, sofa, q],
    queryFn: () => api.games({ date, country, sofa, q }),
    enabled: !!date || (q?.length ?? 0) >= 2,
  });

  const dateIdx = date ? dates.indexOf(date) : -1;
  const olderDate = dateIdx >= 0 ? dates[dateIdx + 1] : undefined;
  const newerDate = dateIdx > 0 ? dates[dateIdx - 1] : undefined;

  const clearSearch = () => update({ q: undefined, date: dates[0] });

  const rows = games.data ?? [];
  const matched = rows.filter((g) => g.sofa_event_id != null).length;

  const columns = useMemo<ColumnDef<GameRow, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      {
        id: 'kickoff', header: 'Kickoff (UTC)', accessorFn: (g) => g.kickoff, meta: { align: 'left' },
        cell: ({ row }) => (
          <span className="num">{searchMode ? formatKickoff(row.original.kickoff) : formatTime(row.original.kickoff)}</span>
        ),
      },
      {
        id: 'home_team', header: 'Home', accessorKey: 'home_team', meta: { align: 'right' },
        cell: ({ row }) => <Text fw={500}>{row.original.home_team}</Text>,
      },
      {
        id: 'score', header: 'Score', accessorFn: (g) => g.score_home, meta: { align: 'center' },
        cell: ({ row }) => (
          <Badge variant="default" className="num">{formatScore(row.original.score_home, row.original.score_away)}</Badge>
        ),
      },
      {
        id: 'away_team', header: 'Away', accessorKey: 'away_team', meta: { align: 'left' },
        cell: ({ row }) => <Text fw={500}>{row.original.away_team}</Text>,
      },
      {
        id: 'league', header: 'League', accessorKey: 'league', meta: { align: 'left' },
        cell: ({ row }) => (
          <div>
            <Text size="sm">{row.original.league}</Text>
            {row.original.country && <Text size="xs" c="dimmed">{row.original.country}</Text>}
          </div>
        ),
      },
      { id: 'bookmakers', header: 'Books', accessorKey: 'bookmakers', meta: { align: 'center' } },
      {
        id: 'sofa_event_id', header: 'Sofa', accessorKey: 'sofa_event_id', meta: { align: 'center' },
        cell: ({ row }) =>
          row.original.sofa_event_id != null ? (
            <Tooltip label={`Sofa event ${row.original.sofa_event_id}`}>
              <Badge color="teal" variant="light">Matched</Badge>
            </Tooltip>
          ) : (
            <Badge color="gray" variant="outline">Unmatched</Badge>
          ),
      },
      {
        id: 'id', header: 'ID', accessorKey: 'id', meta: { align: 'right' },
        cell: ({ row }) => <Text size="xs" c="dimmed">{row.original.id}</Text>,
      },
    ],
    [searchMode],
  );

  const toIso = (d: unknown) => dayjs(d as string | Date).format('YYYY-MM-DD');

  return (
    <>
      <PageHeader
        title="Games"
        description={
          searchMode
            ? `Search results for “${q}” (all dates, newest first, max 200)`
            : date
              ? formatDateLong(date)
              : undefined
        }
      />
      <Paper withBorder p="sm" mb="md">
        <Group gap="sm" wrap="wrap">
          <Group gap={4} wrap="nowrap">
            <Tooltip label="Older day">
              <ActionIcon
                variant="default" aria-label="Older day" disabled={!olderDate}
                onClick={() => olderDate && update({ date: olderDate, q: undefined })}
              >
                <IconChevronLeft size={16} />
              </ActionIcon>
            </Tooltip>
            <DatePickerInput
              w={200}
              placeholder="Pick a date"
              valueFormat="ddd D MMM YYYY"
              value={date ?? null}
              minDate={dates.length ? dates[dates.length - 1] : undefined}
              maxDate={dates.length ? dates[0] : undefined}
              excludeDate={(d) => !dateSet.has(toIso(d))}
              onChange={(v) => v && update({ date: toIso(v), q: undefined })}
            />
            <Tooltip label="Newer day">
              <ActionIcon
                variant="default" aria-label="Newer day" disabled={!newerDate}
                onClick={() => newerDate && update({ date: newerDate, q: undefined })}
              >
                <IconChevronRight size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
          <Select
            placeholder="All countries" data={filters.data?.countries ?? []} searchable clearable w={200}
            value={country ?? null} onChange={(v) => update({ country: v ?? undefined })}
          />
          <SegmentedControl
            value={sofa}
            onChange={(v) => update({ sofa: v === 'all' ? undefined : v })}
            data={[
              { label: 'All', value: 'all' },
              { label: 'Matched', value: 'matched' },
              { label: 'Unmatched', value: 'unmatched' },
            ]}
          />
          <TextInput
            placeholder="Filter this list…" leftSection={<IconFilter size={14} />}
            value={localFilter} onChange={(e) => setLocalFilter(e.currentTarget.value)}
          />
          {q && (
            <Badge size="lg" variant="light" rightSection={<CloseButton size="xs" aria-label="Clear search" onClick={clearSearch} />}>
              Search: {q}
            </Badge>
          )}
        </Group>
      </Paper>
      <Group gap="xs" mb="sm">
        <Badge variant="default">{rows.length} games</Badge>
        <Badge color="teal" variant="light">{matched} matched</Badge>
        <Badge color="gray" variant="light">{rows.length - matched} unmatched</Badge>
      </Group>
      <QueryState query={games}>
        <DataTable<GameRow>
          data={rows}
          columns={columns}
          globalFilter={localFilter}
          pageSize={100}
          initialSorting={[{ id: 'kickoff', desc: !date }]}
          onRowClick={(g) => navigate(`/games/${g.id}`)}
          emptyText="No games found for the selected filters."
        />
      </QueryState>
    </>
  );
}
