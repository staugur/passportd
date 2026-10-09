/**
 * 通用分页组件（基于 Bulma 官方 Pagination 组件）
 *
 * 结构遵循 Bulma 规范：
 *   nav.pagination[.is-small] > a.pagination-previous
 *                             + a.pagination-next
 *                             + ul.pagination-list > li > a.pagination-link
 *   （当前页 a.pagination-link.is-current[aria-current=page]；
 *     不可用的上一页/下一页加 .is-disabled；区间分隔用 li > span.pagination-ellipsis）
 *
 * 使用：
 *   PassportPager.render($('#pager'), {
 *       page: 1, pages: 5, perPage: 10, total: 100,
 *       onChange: function (page, perPage) { ... }
 *   });
 */
(function (window, $) {
    'use strict';

    //: 可选的每页条数（默认 10）
    let PAGE_SIZES = [10, 20, 50, 100];

    /**
     * 生成页码序列，页数较多时用省略号（null 表示省略号）收敛
     * @param {number} page 当前页
     * @param {number} pages 总页数
     * @returns {Array} 页码与 null 组成的数组
     */
    function pageNumbers(page, pages) {
        if (pages <= 7) {
            let all = [];
            for (let i = 1; i <= pages; i++) {
                all.push(i);
            }
            return all;
        }
        let wanted = [1, page - 1, page, page + 1, pages].filter(function (v) {
            return v >= 1 && v <= pages;
        });
        wanted = wanted.filter(function (v, i, arr) {
            return arr.indexOf(v) === i;
        }).sort(function (a, b) {
            return a - b;
        });
        let out = [];
        let prev = 0;
        wanted.forEach(function (v) {
            if (prev && v - prev > 1) {
                out.push(null);
            }
            out.push(v);
            prev = v;
        });
        return out;
    }

    /**
     * 渲染分页组件到指定容器
     * @param {Object} $container jQuery 容器
     * @param {Object} opts {page, pages, perPage, total, onChange}
     */
    function render($container, opts) {
        let page = Math.max(1, opts.page || 1);
        let pages = Math.max(1, opts.pages || 1);
        let perPage = opts.perPage || 10;
        let total = opts.total || 0;

        let options = PAGE_SIZES.map(function (size) {
            return '<option value="' + size + '"'
                + (size === perPage ? ' selected' : '') + '>' + size + ' 条/页</option>';
        }).join('');

        // 页码列表：当前页加 is-current 与 aria-current
        let links = pageNumbers(page, pages).map(function (p) {
            if (p === null) {
                return '<li><span class="pagination-ellipsis">&hellip;</span></li>';
            }
            if (p === page) {
                return '<li><a class="pagination-link is-current"'
                    + ' aria-label="第 ' + p + ' 页" aria-current="page">' + p + '</a></li>';
            }
            return '<li><a class="pagination-link" aria-label="跳转到第 ' + p + ' 页"'
                + ' data-page="' + p + '">' + p + '</a></li>';
        }).join('');

        // 上一页 / 下一页：到边界时加 is-disabled（并标注 title、去掉 tab 焦点）
        let prevCls = 'pagination-previous' + (page <= 1 ? ' is-disabled' : '');
        let nextCls = 'pagination-next' + (page >= pages ? ' is-disabled' : '');
        let prevAttr = page <= 1
            ? ' aria-disabled="true" tabindex="-1" title="已是第一页"'
            : ' data-page="' + (page - 1) + '"';
        let nextAttr = page >= pages
            ? ' aria-disabled="true" tabindex="-1" title="已是最后一页"'
            : ' data-page="' + (page + 1) + '"';

        let html = ''
            + '<div class="is-flex is-justify-content-space-between is-align-items-center mb-2">'
            + '  <div class="select is-small">'
            + '    <select class="js-page-size" aria-label="每页数量">' + options + '</select></div>'
            + '  <span class="has-text-grey is-size-7">共 ' + total
            + ' 条，第 ' + page + ' / ' + pages + ' 页</span>'
            + '</div>'
            + '<nav class="pagination is-small" role="navigation" aria-label="分页">'
            + '  <a class="' + prevCls + '"' + prevAttr + '>上一页</a>'
            + '  <a class="' + nextCls + '"' + nextAttr + '>下一页</a>'
            + '  <ul class="pagination-list">' + links + '</ul>'
            + '</nav>';

        $container.html(html);

        function go(target) {
            let target_ = parseInt(target, 10);
            if (!target_) {
                return;
            }
            target_ = Math.max(1, Math.min(target_, pages));
            if (target_ === page) {
                return;
            }
            opts.onChange(target_, perPage);
        }

        $container.find('.pagination-link').on('click', function () {
            go($(this).data('page'));
        });
        $container.find('.pagination-previous').on('click', function () {
            if (page > 1) {
                go(page - 1);
            }
        });
        $container.find('.pagination-next').on('click', function () {
            if (page < pages) {
                go(page + 1);
            }
        });
        $container.find('.js-page-size').on('change', function () {
            opts.onChange(1, parseInt($(this).val(), 10));
        });
    }

    window.PassportPager = { render: render };
})(window, jQuery);
