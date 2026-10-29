import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type RuleChanges, type RuleCondition } from "../api";
import { CategorySelect } from "../components/CategorySelect";
import { DIRECTION_LABELS, MATCH_LABELS, RuleFields } from "../components/RuleFields";
import { invalidateLedger } from "../queries";

const EMPTY: RuleCondition = { match_field: "merchant", pattern: "", direction: null };

export function RulesPage() {
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: Infinity });
  const [draft, setDraft] = useState<RuleCondition>(EMPTY);
  const [categoryId, setCategoryId] = useState("");

  const onChanged = () => void invalidateLedger(queryClient);
  const create = useMutation({
    mutationFn: () => api.saveRule({ ...draft, category_id: categoryId }),
    onSuccess: () => {
      setDraft({ ...draft, pattern: "" });
      setCategoryId("");
      onChanged();
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: RuleChanges }) => api.editRule(id, changes),
    onSuccess: onChanged,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteRule(id), onSuccess: onChanged });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.pattern.trim() && categoryId) create.mutate();
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>分类规则</h1>
          <p className="page-subtitle">
            规则比自动分类优先，单笔交易上手动改的分类又比规则优先。规则一改，所有历史交易会立即重新归类。
          </p>
        </div>
      </header>

      <section className="panel">
        <div className="panel-header">
          <h2>新建规则</h2>
        </div>
        <form className="rule-form" onSubmit={submit}>
          <RuleFields value={draft} onChange={setDraft} />
          <div className="rule-form-target">
            <label htmlFor="new-rule-category">归入</label>
            <CategorySelect
              id="new-rule-category"
              categories={categories.data ?? []}
              value={categoryId}
              onChange={setCategoryId}
              placeholder="选择分类"
            />
            <button type="submit" className="primary" disabled={!draft.pattern.trim() || !categoryId || create.isPending}>
              {create.isPending ? "保存中…" : "添加规则"}
            </button>
          </div>
          {create.error && <p className="error">{create.error.message}</p>}
        </form>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>我的规则</h2>
          {rules.data && rules.data.length > 0 && <span className="muted">{rules.data.length} 条</span>}
        </div>
        {(edit.error ?? remove.error) && <p className="error small">{(edit.error ?? remove.error)?.message}</p>}
        {rules.data && rules.data.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>条件</th>
                  <th>归入分类</th>
                  <th className="num">目前影响</th>
                  <th>
                    <span className="visually-hidden">操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rules.data.map((rule) => (
                  <tr key={rule.id}>
                    <td className="wrap">
                      {MATCH_LABELS[rule.match_field]} <strong>{rule.pattern}</strong>
                      {rule.direction && <span className="tag">{DIRECTION_LABELS[rule.direction]}</span>}
                    </td>
                    <td>
                      <CategorySelect
                        label={`「${rule.pattern}」归入的分类`}
                        categories={categories.data ?? []}
                        value={rule.category_id}
                        onChange={(id) => edit.mutate({ id: rule.id, changes: { category_id: id } })}
                      />
                    </td>
                    <td className="num">{rule.transaction_count} 笔</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="text-button danger"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`删除规则「${MATCH_LABELS[rule.match_field]} ${rule.pattern}」？对应的交易会回到自动分类。`)) {
                            remove.mutate(rule.id);
                          }
                        }}
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">
            {rules.isPending
              ? "加载中…"
              : "还没有规则。在交易详情里改分类时勾选「以后同样的交易也归入这个分类」，或者在上面新建。"}
          </p>
        )}
      </section>
    </>
  );
}
