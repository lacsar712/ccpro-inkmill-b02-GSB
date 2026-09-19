<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { millStatusLabel } from '../lib/labels';
  import type { Mill, MillStatus, Workshop } from '../lib/types';

  let rows: Mill[] = [];
  let workshops: Workshop[] = [];
  let error = '';
  let editingId: number | null = null;

  let selected = new Set<number>();
  let batchStatus: MillStatus = 'idle';

  let form = {
    workshopId: '',
    millCode: '',
    pigmentBase: '',
    bowlLiters: '25',
    status: 'idle' as MillStatus,
  };

  async function load() {
    error = '';
    try {
      [rows, workshops] = await Promise.all([
        api<Mill[]>('/mills'),
        api<Workshop[]>('/workshops'),
      ]);
    } catch (e) {
      error = e instanceof Error ? e.message : '加载失败';
    }
  }

  onMount(load);

  function workshopName(id: number): string {
    return workshops.find((w) => w.id === id)?.name || `#${id}`;
  }

  function reset() {
    form = {
      workshopId: workshops[0] ? String(workshops[0].id) : '',
      millCode: '',
      pigmentBase: '',
      bowlLiters: '25',
      status: 'idle',
    };
    editingId = null;
  }

  function edit(row: Mill) {
    editingId = row.id;
    form = {
      workshopId: String(row.workshopId),
      millCode: row.millCode,
      pigmentBase: row.pigmentBase,
      bowlLiters: String(row.bowlLiters),
      status: row.status,
    };
  }

  async function save() {
    error = '';
    const payload = {
      workshopId: Number(form.workshopId),
      millCode: form.millCode,
      pigmentBase: form.pigmentBase,
      bowlLiters: Number(form.bowlLiters),
      status: form.status,
    };
    try {
      if (editingId) {
        await api(`/mills/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) });
      } else {
        await api('/mills', { method: 'POST', body: JSON.stringify(payload) });
      }
      reset();
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '保存失败';
    }
  }

  async function remove(id: number) {
    if (!confirm('确认删除该研磨机？')) return;
    try {
      await api(`/mills/${id}`, { method: 'DELETE' });
      selected.delete(id);
      selected = selected;
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '删除失败';
    }
  }

  function toggle(id: number) {
    if (selected.has(id)) {
      selected.delete(id);
    } else {
      selected.add(id);
    }
    selected = selected;
  }

  function toggleAll() {
    if (selected.size === rows.length) {
      selected = new Set();
    } else {
      selected = new Set(rows.map((r) => r.id));
    }
  }

  async function applyBatch() {
    error = '';
    if (selected.size === 0) {
      error = '请先勾选要批量更新的研磨机';
      return;
    }
    try {
      // 校验全部在服务端完成；失败时不改动本地行，仅展示后端中文错误
      await api<{ updated: number }>('/mills/batch-status', {
        method: 'POST',
        body: JSON.stringify({ millIds: [...selected], status: batchStatus }),
      });
      selected = new Set();
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '批量更新失败';
    }
  }
</script>

<header class="page-head">
  <h1>研磨机</h1>
  <p>机台编号在同一车间内唯一；状态机：待机→研磨/清洗，研磨→清洗/待机，清洗→待机；同一车间最多一台研磨中</p>
</header>

{#if error}
  <div class="err">{error}</div>
{/if}

<section class="panel">
  <h2>{editingId ? '编辑研磨机' : '新增研磨机'}</h2>
  <div class="fields">
    <div class="field">
      <label>所属车间
        <select bind:value={form.workshopId}>
          {#each workshops as w}
            <option value={String(w.id)}>{w.name}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field"><label>机台编号<input bind:value={form.millCode} /></label></div>
    <div class="field"><label>色浆基料<input bind:value={form.pigmentBase} /></label></div>
    <div class="field"><label>料碗容量(L)<input type="number" step="0.1" bind:value={form.bowlLiters} /></label></div>
    <div class="field">
      <label>状态
        <select bind:value={form.status}>
          <option value="grinding">研磨中</option>
          <option value="idle">待机</option>
          <option value="wash">清洗</option>
        </select>
      </label>
    </div>
  </div>
  <div class="actions">
    <button class="btn-primary" on:click={save}>{editingId ? '保存' : '创建'}</button>
    {#if editingId}
      <button class="btn-ghost" on:click={reset}>取消</button>
    {/if}
  </div>
</section>

<section class="panel">
  <h2>批量状态切换</h2>
  <div class="actions">
    <span>已选 {selected.size} 台</span>
    <select bind:value={batchStatus}>
      <option value="grinding">研磨中</option>
      <option value="idle">待机</option>
      <option value="wash">清洗</option>
    </select>
    <button class="btn-primary" on:click={applyBatch} disabled={selected.size === 0}>
      批量更新状态
    </button>
  </div>
</section>

<section class="panel">
  <table class="data-table">
    <thead>
      <tr>
        <th>
          <input
            type="checkbox"
            checked={rows.length > 0 && selected.size === rows.length}
            on:change={toggleAll}
          />
        </th>
        <th>ID</th>
        <th>车间</th>
        <th>编号</th>
        <th>基料</th>
        <th>容量(L)</th>
        <th>状态</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row}
        <tr>
          <td>
            <input
              type="checkbox"
              checked={selected.has(row.id)}
              on:change={() => toggle(row.id)}
            />
          </td>
          <td>{row.id}</td>
          <td>{workshopName(row.workshopId)}</td>
          <td>{row.millCode}</td>
          <td>{row.pigmentBase}</td>
          <td>{row.bowlLiters}</td>
          <td><span class="badge {row.status}">{millStatusLabel[row.status]}</span></td>
          <td class="ops">
            <button class="link-btn" on:click={() => edit(row)}>编辑</button>
            <button class="link-btn danger" on:click={() => remove(row.id)}>删除</button>
          </td>
        </tr>
      {:else}
        <tr><td colspan="8">暂无数据</td></tr>
      {/each}
    </tbody>
  </table>
</section>
