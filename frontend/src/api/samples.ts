/* ============================================================
 * 示例问题（静态） — 供输入框快捷填充
 * 知识点全部对齐 test_docs 文档集（01 企业行政制度库 / 02 产品与技术文档库 / 03 IT 运维与安全知识库）
 * ============================================================ */

export interface SampleQuestion {
  id: string
  label: string
  question: string
}

export const SAMPLE_QUESTIONS: SampleQuestion[] = [
  { id: 'attendance', label: '考勤制度', question: '迟到是怎么认定和处罚的？' },
  { id: 'annual-leave', label: '休假福利', question: '工作满十年的员工年假有几天？' },
  { id: 'travel', label: '差旅报销', question: '普通员工去上海出差，住宿费报销上限是多少？' },
  { id: 'org', label: '组织架构', question: '产品研发中心下设哪几个组，各自负责什么？' },
  { id: 'rag', label: '技术原理', question: '对比一下向量检索和 BM25 关键词检索的区别与适用场景' },
  { id: 'db-recovery', label: '数据恢复', question: '误删了数据表，还能恢复到误操作之前的状态吗？' },
]
