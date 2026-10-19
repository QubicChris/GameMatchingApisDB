import { useState, type ReactNode } from 'react';
import {
  flexRender, getCoreRowModel, getFilteredRowModel, getPaginationRowModel, getSortedRowModel,
  useReactTable, type ColumnDef, type RowData, type SortingState,
} from '@tanstack/react-table';
import { Center, Group, Pagination, ScrollArea, Table, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronUp, IconSelector } from '@tabler/icons-react';

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    align?: 'left' | 'center' | 'right';
  }
}

export interface DataTableProps<T> {
  data: T[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  globalFilter?: string;
  pageSize?: number;
  initialSorting?: SortingState;
  onRowClick?: (row: T) => void;
  emptyText?: ReactNode;
  maxHeight?: number;
}

export function DataTable<T>({
  data, columns, globalFilter = '', pageSize = 50, initialSorting = [], onRowClick, emptyText = 'No rows.', maxHeight,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize });
  const table = useReactTable({
    data, columns,
    state: { sorting, globalFilter, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    globalFilterFn: 'includesString',
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const rows = table.getRowModel().rows;
  const total = table.getFilteredRowModel().rows.length;

  return (
    <>
      <ScrollArea.Autosize mah={maxHeight}>
        <Table striped highlightOnHover={!!onRowClick} stickyHeader verticalSpacing="xs">
          <Table.Thead>
            {table.getHeaderGroups().map((hg) => (
              <Table.Tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  const Icon = sorted === 'asc' ? IconChevronUp : sorted === 'desc' ? IconChevronDown : IconSelector;
                  const align = h.column.columnDef.meta?.align ?? 'left';
                  return (
                    <Table.Th key={h.id} style={{ textAlign: align, whiteSpace: 'nowrap' }}>
                      {h.isPlaceholder ? null : h.column.getCanSort() ? (
                        <UnstyledButton onClick={h.column.getToggleSortingHandler()}>
                          <Group gap={4} wrap="nowrap" justify={align === 'right' ? 'flex-end' : 'flex-start'}>
                            <Text fw={600} size="sm">{flexRender(h.column.columnDef.header, h.getContext())}</Text>
                            <Icon size={14} stroke={1.5} />
                          </Group>
                        </UnstyledButton>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </Table.Th>
                  );
                })}
              </Table.Tr>
            ))}
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={columns.length}>
                  <Center py="lg"><Text c="dimmed">{emptyText}</Text></Center>
                </Table.Td>
              </Table.Tr>
            ) : (
              rows.map((row) => (
                <Table.Tr
                  key={row.id}
                  className={onRowClick ? 'clickable-row' : undefined}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <Table.Td key={cell.id} style={{ textAlign: cell.column.columnDef.meta?.align ?? 'left' }}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </ScrollArea.Autosize>
      {table.getPageCount() > 1 && (
        <Group justify="space-between" mt="sm">
          <Text size="sm" c="dimmed">{total.toLocaleString('en-US')} rows</Text>
          <Pagination
            size="sm"
            total={table.getPageCount()}
            value={pagination.pageIndex + 1}
            onChange={(p) => table.setPageIndex(p - 1)}
          />
        </Group>
      )}
    </>
  );
}
