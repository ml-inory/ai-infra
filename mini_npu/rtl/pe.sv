`default_nettype none
`timescale 1ns/1ns

// load w if load is high
// psum_out = psum_in + a * w
//
// 语义（psum_in 是正常的外部输入，模块内部不含反馈）:
//     load=1 : 把 w 装入 w_inner，psum_out 保持
//     load=0 : psum_out <= psum_in + $signed(a) * $signed(w_inner)
//
// 注意: psum_in 由外部提供（例如上一级 PE 的部分和），
//       不要把本模块自己的 psum_out 绕回来当 psum_in。
module PE #(
    parameter A_BITS = 8,
    parameter W_BITS = 8,
    parameter ACC_BITS = 32
) (
    input wire clk,
    input wire rst,
    input wire load,
    input reg [A_BITS-1:0] a,
    input reg [W_BITS-1:0] w,
    input reg [ACC_BITS-1:0] psum_in,
    output reg [ACC_BITS-1:0] psum_out
);
    reg [W_BITS-1:0] w_inner;

    // 有符号操作数先各自符号扩展到 ACC_BITS 再相乘。
    //
    // 不能写成 "psum_out <= psum_in + $signed(a) * $signed(w_inner)"：
    // 在 unsigned 的加法上下文里，乘法结果会被当作无符号数处理，负权重乘出
    // 来的负积会被当成大正数。实测 a=2,w=-4 会得到 504 而不是 -8。
    wire signed [ACC_BITS-1:0] a_ext  = $signed(a);
    wire signed [ACC_BITS-1:0] w_ext  = $signed(w_inner);
    wire signed [2*ACC_BITS-1:0] prod = a_ext * w_ext;
    wire signed [ACC_BITS-1:0] psum_s = $signed(psum_in);

    always @(posedge clk ) begin 
        if (rst) begin
            w_inner <= 0;
            psum_out <= 0;
        end 
        else begin
            if (load) begin
                w_inner <= w;
            end else begin
                psum_out <= psum_s + prod[ACC_BITS-1:0];
            end
        end
    end
endmodule