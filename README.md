# Thu ngân Offline — Flask + SQLite

## Chức năng
- Đăng nhập, đăng ký tài khoản nhân viên và đăng xuất.
- Tìm sản phẩm theo tên hoặc mã vạch.
- Thêm/sửa sản phẩm và tồn kho (chỉ Admin).
- Chọn sản phẩm, thay đổi số lượng và tự tính tổng tiền.
- Thanh toán tiền mặt, tính tiền thừa hoặc xác nhận chuyển khoản thủ công.
- Lưu hóa đơn, xem lịch sử, xem/in chi tiết hóa đơn.
- Tự động trừ tồn kho sau khi thanh toán thành công.

## Chạy trên Windows
Mở Terminal trong thư mục có `app.py`, chạy:
```bash
py -m pip install -r requirements.txt
py app.py
```
Mở `http://127.0.0.1:5000`.


Nếu dùng file `pos.db` có sẵn trong gói, hãy dùng tài khoản đã có trong cơ sở dữ liệu đó. Không xóa `pos.db` nếu muốn giữ sản phẩm và hóa đơn.
