import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Checkbox, Code, CopyButton, Group, List, MultiSelect, Paper, SimpleGrid, Stack, Table,
  Text, Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconCopy, IconDownload } from '@tabler/icons-react';
import { api } from '../api/client';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { cliCommand, EXPORT_SHEETS, ODDS_SHEETS, presetRange, type RangePreset } from '../lib/exportRanges';
import { formatNumber } from '../lib/format';

const PRESETS: { label: string; value: RangePreset }[] = [
  { label: 'Latest day', value: 'latest' },
  { label: 'Last 7 days', value: 'last7' },
  { label: 'Last 30 days', value: 'last30' },
];

export function ExportPage() {
  const filters = useQuery({ queryKey: ['filters'], queryFn: api.filters });
  const dates = filters.data?.dates ?? [];
  const newest = dates[0];
  const oldest = dates[dates.length - 1];

  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const [countries, setCountries] = useState<string[]>([]);
  const [leagues, setLeagues] = useState<string[]>([]);
  const [umids, setUmids] = useState<string[]>([]);
  const [sheets, setSheets] = useState<string[]>([...EXPORT_SHEETS]);
  const [downloading, setDownloading] = useState(false);

  const matchRates = useQuery({ queryKey: ['match-rates'], queryFn: api.matchRates });
  const marketTypes = useQuery({ queryKey: ['market-types'], queryFn: api.marketTypes });

  const leagueOptions = useMemo(() => {
    const names = new Set<string>();
    for (const l of matchRates.data?.leagues ?? []) {
      if (countries.length === 0 || countries.includes(l.country)) names.add(l.league);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [matchRates.data, countries]);

  useEffect(() => {
    setLeagues((cur) => {
      const next = cur.filter((l) => leagueOptions.includes(l));
      return next.length === cur.length ? cur : next;
    });
  }, [leagueOptions]);

  const marketOptions = (marketTypes.data ?? []).map((m) => ({
    value: String(m.umid),
    label: `${m.canonical_name ?? 'Market ' + m.umid} (#${m.umid})`,
  }));

  useEffect(() => {
    if (range[0] == null && range[1] == null && dates.length > 0) {
      setRange(presetRange('last7', dates) ?? [null, null]);
    }
  }, [dates]); // eslint-disable-line react-hooks/exhaustive-deps

  const [from, to] = range;
  const ready = !!from && !!to;
  const noSheets = sheets.length === 0;

  const params = {
    date_from: from as string,
    date_to: to as string,
    include_odds: true,
    countries,
    leagues,
    umids: umids.map(Number),
    sheets: sheets.length === EXPORT_SHEETS.length ? [] : sheets,
  };

  const preview = useQuery({
    queryKey: ['export-preview', params],
    queryFn: () => api.exportPreview(params),
    enabled: ready && !noSheets,
  });
  const p = preview.data;
  const cli = ready
    ? cliCommand(from as string, to as string, { countries, leagues, umids: umids.map(Number), sheets })
    : '';

  const download = async () => {
    if (!from || !to) return;
    setDownloading(true);
    try {
      const { blob, filename } = await api.downloadExport(params);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      notifications.show({ color: 'teal', title: 'Export ready', message: filename });
    } catch (err) {
      notifications.show({
        color: 'red', title: 'Export failed', message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Export to Excel"
        description="Download every table for a kickoff date range as one workbook with readable column names."
      />
      <Stack gap="md" maw={760}>
        <Paper withBorder p="lg">
          <Stack gap="sm">
            <DatePickerInput
              type="range"
              label="Kickoff dates (UTC)"
              value={range}
              onChange={(v) => setRange([v[0] as string | null, v[1] as string | null])}
              minDate={oldest}
              maxDate={newest}
              valueFormat="D MMM YYYY"
              w={320}
            />
            <Group gap="xs">
              {PRESETS.map((pr) => (
                <Button
                  key={pr.value} variant="default" size="xs"
                  onClick={() => {
                    const r = presetRange(pr.value, dates);
                    if (r) setRange(r);
                  }}
                >
                  {pr.label}
                </Button>
              ))}
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">Filters</Title>
          <Stack gap="sm">
            <MultiSelect
              label="Countries" placeholder="All countries"
              data={filters.data?.countries ?? []} value={countries} onChange={setCountries}
              searchable clearable
            />
            <MultiSelect
              label="Leagues" placeholder="All leagues"
              data={leagueOptions} value={leagues} onChange={setLeagues}
              searchable clearable
            />
            <MultiSelect
              label="Markets" placeholder="All markets"
              description="Applies to Odds, Exchange Ladder and Sofa Odds"
              data={marketOptions} value={umids} onChange={setUmids}
              searchable clearable
            />
            <Checkbox.Group label="Sheets" value={sheets} onChange={setSheets}>
              <SimpleGrid cols={{ base: 1, sm: 2 }} mt="xs" spacing="xs">
                {EXPORT_SHEETS.map((name) => (
                  <Checkbox key={name} value={name} label={name} />
                ))}
              </SimpleGrid>
            </Checkbox.Group>
            <Group gap="xs">
              <Button variant="default" size="xs" onClick={() => setSheets([...EXPORT_SHEETS])}>All</Button>
              <Button
                variant="default" size="xs"
                onClick={() => setSheets(EXPORT_SHEETS.filter((n) => !ODDS_SHEETS.includes(n)))}
              >
                No odds sheets
              </Button>
            </Group>
            {noSheets && <Text c="red" size="sm">Pick at least one sheet.</Text>}
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">Preview</Title>
          {!ready ? (
            <Text c="dimmed" size="sm">Pick a date range to see what will be exported.</Text>
          ) : (
            <QueryState query={preview}>
              {p && (
                <Stack gap="sm">
                  <Table>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Sheet</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>Rows</Table.Th>
                        <Table.Th />
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {p.sheets.map((s) => (
                        <Table.Tr key={s.name}>
                          <Table.Td>{s.name}</Table.Td>
                          <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(s.rows)}</Table.Td>
                          <Table.Td>
                            {p.too_large.includes(s.name) && <Badge color="red">Too large</Badge>}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                  <Text size="xs" c="dimmed">
                    {`Max ${formatNumber(p.max_rows)} rows per sheet. Team Aliases and Market Types always include all rows.`}
                  </Text>
                  {!p.ok && (
                    <Alert color="red" title="Range too large for Excel">
                      Shorten the date range, add filters or leave out odds sheets.
                    </Alert>
                  )}
                </Stack>
              )}
            </QueryState>
          )}
          <Group mt="md">
            <Button
              size="md" leftSection={<IconDownload size={18} />}
              disabled={!p?.ok || noSheets} loading={downloading} onClick={download}
            >
              Download Excel
            </Button>
          </Group>
          <Text size="xs" c="dimmed" mt="xs">
            Large exports can take a minute or two. Filters and fewer sheets make them faster.
          </Text>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">What&apos;s in the workbook</Title>
          <List size="sm" spacing={2}>
            <List.Item>Summary</List.Item>
            <List.Item>Games</List.Item>
            <List.Item>Bookmaker Games</List.Item>
            <List.Item>Odds (one column per bookmaker, best price, Sofa closing odds and result)</List.Item>
            <List.Item>Exchange Ladder (back/lay prices &amp; sizes)</List.Item>
            <List.Item>Sofa Odds</List.Item>
            <List.Item>Match Stats (every stat, home/away, per period)</List.Item>
            <List.Item>Incidents</List.Item>
            <List.Item>Match Rates</List.Item>
            <List.Item>Team Aliases</List.Item>
            <List.Item>Market Types</List.Item>
          </List>
        </Paper>

        {ready && (
          <Paper withBorder p="lg">
            <Title order={5} mb="sm">Command line</Title>
            <CopyButton value={cli}>
              {({ copied, copy }) => (
                <Group wrap="nowrap" align="flex-start">
                  <Code block style={{ flex: 1 }}>{cli}</Code>
                  <Button
                    variant="default" size="xs" onClick={copy}
                    leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </Group>
              )}
            </CopyButton>
          </Paper>
        )}
      </Stack>
    </>
  );
}
