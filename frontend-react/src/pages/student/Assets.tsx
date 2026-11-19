import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../api';
import { useAuth } from '../../auth';
import type { Asset } from '../../types';
import { Async, Field, Select, Table, money, today, useAction, useLoad, usePageTitle } from '../../ui';

export default function Assets() {
  usePageTitle('My assets');
  const { meta } = useAuth();
  const list = useLoad(() => api<Asset[]>('/assets'), []);
  const { run, busy } = useAction();
  const [f, setF] = useState({ category: '', name: '', make_model: '', serial_number: '', purchase_date: '', declared_value: '', proof_of_purchase_ref: '' });
  const [er, setEr] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.category) x.category = 'Choose a category';
    if (!f.name.trim()) x.name = 'Enter a name';
    if (!f.purchase_date) x.purchase_date = 'Enter the purchase date'; else if (f.purchase_date > today()) x.purchase_date = 'Purchase date cannot be in the future';
    if (!(Number(f.declared_value) > 0)) x.declared_value = 'Enter a value greater than 0';
    setEr(x);
    if (Object.keys(x).length) return;
    if (await run(() => api('/assets', { method: 'POST', body: { ...f, declared_value: Number(f.declared_value) } }), 'Asset added')) {
      setF({ category: '', name: '', make_model: '', serial_number: '', purchase_date: '', declared_value: '', proof_of_purchase_ref: '' }); list.reload();
    }
  };
  return (
    <>
      <h1>My assets</h1>
      <Async state={list}>{rows => (
        <Table caption="Registered assets" head={['Name', 'Category', 'Make / model', 'Purchased', 'Declared value']} numCols={[4]}>
          {rows.map(a => <tr key={a.id}><td>{a.name}</td><td>{a.category}</td><td>{a.make_model}</td><td>{a.purchase_date}</td><td className="num">{money(a.declared_value)}</td></tr>)}
        </Table>
      )}</Async>
      <h2>Add an asset</h2>
      <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Add asset">
        <div className="grid cols">
          <Select label="Category" value={f.category} onChange={set('category')} options={meta?.asset_categories ?? []} placeholder="Select…" error={er.category} required />
          <Field label="Name" value={f.name} onChange={set('name')} error={er.name} maxLength={120} required />
          <Field label="Make / model" value={f.make_model} onChange={set('make_model')} />
          <Field label="Serial number" value={f.serial_number} onChange={set('serial_number')} />
          <Field label="Purchase date" type="date" max={today()} value={f.purchase_date} onChange={set('purchase_date')} error={er.purchase_date} required />
          <Field label="Declared value (INR)" type="number" min="1" step="0.01" value={f.declared_value} onChange={set('declared_value')} error={er.declared_value} required />
          <Field label="Proof of purchase reference" value={f.proof_of_purchase_ref} onChange={set('proof_of_purchase_ref')} />
        </div>
        <button type="submit" disabled={busy}>Add asset</button>
      </form>
    </>
  );
}
