import { Text } from '@mantine/core';
import { PageHeader } from '../components/PageHeader';

export function ComingSoonPage({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Text c="dimmed">This screen is being rebuilt. Use the Streamlit dashboard meanwhile.</Text>
    </>
  );
}
