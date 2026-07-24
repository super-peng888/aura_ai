import { api } from "./client"

export interface Category {
  id: string
  name: string
  description?: string
  parent_id?: string
  user_id?: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CategoryTreeNode {
  id: string
  name: string
  description?: string
  parent_id?: string
  user_id?: string
  sort_order: number
  doc_count: number
  children: CategoryTreeNode[]
  created_at: string
}

export interface CategoryCreate {
  name: string
  description?: string
  parent_id?: string
}

export interface CategoryUpdate {
  name?: string
  description?: string
  parent_id?: string
  sort_order?: number
}

export interface PaginatedDocuments {
  items: DocumentItem[]
  total: number
  page: number
  page_size: number
}

export interface DocumentItem {
  id: string
  filename: string
  original_name: string
  file_size: number
  mime_type: string
  oss_url: string
  parse_status: "pending" | "running" | "completed" | "failed"
  page_count?: number
  category_id?: string
  created_at: string
  updated_at: string
}

export const categoryApi = {
  /** 获取分类树 */
  getTree(userId?: string) {
    return api.get<CategoryTreeNode[]>("/categories", {
      params: userId ? { user_id: userId } : undefined,
    })
  },

  /** 创建分类 */
  create(data: CategoryCreate, userId?: string) {
    return api.post<Category>("/categories", data, {
      params: userId ? { user_id: userId } : undefined,
    })
  },

  /** 更新分类 */
  update(id: string, data: CategoryUpdate) {
    return api.put<Category>(`/categories/${id}`, data)
  },

  /** 删除分类 */
  delete(id: string, moveToId?: string) {
    return api.delete<{ message: string }>(`/categories/${id}`, {
      params: moveToId ? { move_to_id: moveToId } : undefined,
    })
  },

  /** 获取分类下文档 */
  getDocuments(id: string, page = 1, pageSize = 20) {
    return api.get<PaginatedDocuments>(`/categories/${id}/documents`, {
      params: { page, page_size: pageSize },
    })
  },
}
