import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { TaskDetail, TaskRecord, approveTask, getTask, getTasks, rejectTask } from '../lib/api';

interface TaskStoreState {
  tasks: TaskRecord[];
  selectedTaskId: string | null;
  taskDetails: Record<string, TaskDetail>;
  knownStatuses: Record<string, string>;
  loading: boolean;
  error: string | null;

  loadTasks: (limit?: number) => Promise<TaskRecord[]>;
  loadTask: (taskId: string) => Promise<TaskDetail | null>;
  selectTask: (taskId: string | null) => void;
  noteKnownStatuses: () => void;
  approveTaskById: (taskId: string, note?: string) => Promise<boolean>;
  rejectTaskById: (taskId: string, reason?: string) => Promise<boolean>;
}

export const useTaskStore = create<TaskStoreState>()(persist(
  (set) => ({
    tasks: [],
    selectedTaskId: null,
    taskDetails: {},
    knownStatuses: {},
    loading: false,
    error: null,

    loadTasks: async (limit = 100) => {
      set({ loading: true, error: null });
      try {
        const tasks = await getTasks(limit);
        set((state) => ({
          tasks,
          loading: false,
          taskDetails: Object.fromEntries(
            Object.entries(state.taskDetails).map(([taskId, detail]) => {
              const task = tasks.find((entry) => entry.task_id === taskId);
              if (!task) {
                return [taskId, detail];
              }
              return [
                taskId,
                {
                  ...detail,
                  ...task,
                  children: detail.children,
                },
              ];
            }),
          ),
        }));
        return tasks;
      } catch (error: any) {
        set({ loading: false, error: error?.message || 'Failed to load tasks.' });
        return [];
      }
    },

    loadTask: async (taskId) => {
      try {
        const detail = await getTask(taskId);
        set((state) => ({
          taskDetails: { ...state.taskDetails, [taskId]: detail },
          selectedTaskId: taskId,
        }));
        return detail;
      } catch (error: any) {
        set({ error: error?.message || 'Failed to load task detail.' });
        return null;
      }
    },

    selectTask: (taskId) => set({ selectedTaskId: taskId }),

    noteKnownStatuses: () => set((state) => ({
      knownStatuses: Object.fromEntries(state.tasks.map((task) => [task.task_id, task.status])),
    })),

    approveTaskById: async (taskId, note) => {
      try {
        const res = await approveTask(taskId, { note });
        if (!res.ok) {
          set({ error: res.error || 'Failed to approve task.' });
          return false;
        }
        const tasks = await getTasks(100);
        const detail = await getTask(taskId).catch(() => null);
        set((state) => ({
          tasks,
          taskDetails: detail ? { ...state.taskDetails, [taskId]: detail } : state.taskDetails,
          error: null,
        }));
        return true;
      } catch (error: any) {
        set({ error: error?.message || 'Failed to approve task.' });
        return false;
      }
    },

    rejectTaskById: async (taskId, reason) => {
      try {
        const res = await rejectTask(taskId, { reason });
        if (!res.ok) {
          set({ error: res.error || 'Failed to reject task.' });
          return false;
        }
        const tasks = await getTasks(100);
        const detail = await getTask(taskId).catch(() => null);
        set((state) => ({
          tasks,
          taskDetails: detail ? { ...state.taskDetails, [taskId]: detail } : state.taskDetails,
          error: null,
        }));
        return true;
      } catch (error: any) {
        set({ error: error?.message || 'Failed to reject task.' });
        return false;
      }
    },
  }),
  {
    name: 'neuralclaw-task-store',
    partialize: (state) => ({
      tasks: state.tasks.slice(0, 50),
      selectedTaskId: state.selectedTaskId,
      knownStatuses: state.knownStatuses,
    }),
  },
));
